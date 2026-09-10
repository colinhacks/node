#!/usr/bin/env python3
"""Build and verify the renewed Linux source-only patch package."""

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


BASE = "8af75451e9041cd6058080ad3d4a65546797b418"
FROZEN_TREE = "3166f9876aa2586b4008f7c722ba406e8258d44a"
PUBLIC_HEAD = "f788616cf1515e30a8cce13513dbe8b30e567904"
COMMIT_PGO = "e22d4673456e6dd59f2e246e9b2abd0e38151d5c"
COMMIT_POSITIONS = "99d932a15875728562a62d65a2c0499af0d3953b"
COMMIT_DICTIONARY = "7efdf3f40841ab7b6ff8dcad2fc8f9ce7c8d42d6"
COMMIT_BACKREFS = "e0ecad7bc3c17754a8f1f522fb089e686e00ad33"
COMMIT_TEST_FORMAT = "1769a845456079ffea5bee4dc3503a55ba7f5a73"
COMMIT_ICU = PUBLIC_HEAD


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def run(source, *args, env=None, text=False):
    return subprocess.check_output(
        ["git", "-C", str(source), *map(str, args)], env=env, text=text, stderr=subprocess.PIPE)


def patch_for(source, older, newer, paths=()):
    return run(source, "diff", "--binary", "--full-index", older, newer, "--", *paths)


def commit_patch(source, commit, paths):
    return run(source, "show", "--binary", "--full-index", "--format=", commit, "--", *paths)


def staged_tree(source, base, patches):
    with tempfile.TemporaryDirectory(prefix="linux-source-package-index-") as directory:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        run(source, "read-tree", base, env=env)
        for patch in patches:
            run(source, "apply", "--cached", "--whitespace=nowarn", patch, env=env)
        return run(source, "write-tree", env=env, text=True).strip()


def changed_paths(source, base, patches):
    with tempfile.TemporaryDirectory(prefix="linux-source-package-index-") as directory:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        run(source, "read-tree", base, env=env)
        for patch in patches:
            run(source, "apply", "--cached", "--whitespace=nowarn", patch, env=env)
        return run(source, "diff", "--cached", "--name-only", base, env=env, text=True).splitlines()


def apply_cached(source, env, patch):
    run(source, "apply", "--cached", "--whitespace=nowarn", patch, env=env)


def minimal_after_frozen_dependencies(source, patch_dir, earlier, candidate):
    """Return the smallest renewed-patch subset that applies after frozen patch 18."""
    for count in range(len(earlier) + 1):
        for subset in itertools.combinations(earlier, count):
            with tempfile.TemporaryDirectory(prefix="linux-source-package-index-") as directory:
                env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
                try:
                    run(source, "read-tree", FROZEN_TREE, env=env)
                    for number in subset:
                        apply_cached(source, env, patch_dir / number)
                    apply_cached(source, env, patch_dir / candidate)
                except subprocess.CalledProcessError:
                    continue
            return list(subset)
    raise RuntimeError(f"No prerequisite closure applies {candidate}")


def patch_paths(path):
    return set(re.findall(r"^diff --git a/(.*?) b/", path.read_text(errors="replace"), re.MULTILINE))


def original_dependency_closure(rows, numbers):
    closure = set(numbers)
    pending = list(numbers)
    while pending:
        for dependency in rows[pending.pop() - 1]["dependencies"]:
            if dependency not in closure:
                closure.add(dependency)
                pending.append(dependency)
    return closure


def base_context_applies(source, original, original_rows, original_numbers, patch_dir,
                         additional_names, candidate):
    with tempfile.TemporaryDirectory(prefix="linux-source-package-index-") as directory:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        try:
            run(source, "read-tree", BASE, env=env)
            for number in sorted(original_numbers):
                apply_cached(source, env, original / original_rows[number - 1]["file"])
            for name in additional_names:
                apply_cached(source, env, patch_dir / name)
            apply_cached(source, env, patch_dir / candidate)
            run(source, "diff", "--cached", "--check", env=env)
        except subprocess.CalledProcessError:
            return False
    return True


def minimal_base_context(source, original, original_rows, patch_dir, additional_names, candidate):
    """Trace overlapping frozen files and test minimal closed contexts from BASE."""
    target_paths = patch_paths(patch_dir / candidate)
    roots = [
        number for number, row in enumerate(original_rows, 1)
        if target_paths & patch_paths(original / row["file"])
    ]
    for count in range(len(roots) + 1):
        for subset in itertools.combinations(roots, count):
            context = original_dependency_closure(original_rows, subset)
            if base_context_applies(source, original, original_rows, context, patch_dir,
                                    additional_names, candidate):
                return sorted(context), roots
    raise RuntimeError(f"No traced original-patch closure applies {candidate}")


def build(source, original, output):
    source = source.resolve()
    original = original.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(output)

    frozen = json.loads((original / "manifest.json").read_text())
    if frozen["base"] != BASE or frozen["resulting_tree"] != FROZEN_TREE or len(frozen["patches"]) != 18:
        raise RuntimeError("Original package is not the expected frozen 18-patch series")
    output.mkdir(parents=True)

    rows = json.loads(json.dumps(frozen["patches"]))
    for row in rows:
        data = (original / row["file"]).read_bytes()
        if sha256(data) != row["sha256"]:
            raise RuntimeError(f"Frozen patch drift: {row['file']}")
        (output / row["file"]).write_bytes(data)

    additions = [
        ("19-build-linux-llvm-pgo.patch", patch_for(
            source, FROZEN_TREE, COMMIT_PGO, ["common.gypi", "configure.py"]), {
            "published_commits": [COMMIT_PGO],
            "composition": "The direct PGO commit.",
        }),
        ("20-v8-collect-source-positions.patch", b"".join([
            patch_for(source, COMMIT_PGO, COMMIT_POSITIONS),
            commit_patch(source, COMMIT_TEST_FORMAT, ["test/cctest/test_source_positions_advanced.cc"]),
            commit_patch(source, COMMIT_ICU, ["tools/v8_gypfiles/node_startup_cctest.gyp"]),
        ]), {
            "published_commits": [COMMIT_POSITIONS, COMMIT_TEST_FORMAT, COMMIT_ICU],
            "composition": "Source-position commit, its declaration formatting hunk, and the ICU test dependency.",
        }),
        ("21-v8-bound-dictionary-rehash.patch", b"".join([
            patch_for(source, COMMIT_POSITIONS, COMMIT_DICTIONARY),
            commit_patch(source, COMMIT_TEST_FORMAT, ["test/cctest/test_snapshot_dictionary_rehash.cc"]),
        ]), {
            "published_commits": [COMMIT_DICTIONARY, COMMIT_TEST_FORMAT],
            "composition": "Dictionary commit and its declaration formatting hunk.",
        }),
        ("22-v8-size-deserializer-backrefs.patch", patch_for(source, COMMIT_DICTIONARY, COMMIT_BACKREFS), {
            "published_commits": [COMMIT_BACKREFS],
            "composition": "The direct deserializer back-reference commit.",
        }),
    ]
    for filename, data, provenance in additions:
        if not data:
            raise RuntimeError(f"Empty generated patch: {filename}")
        (output / filename).write_bytes(data)
        rows.append({"file": filename, "sha256": sha256(data), "dependencies": [], **provenance})

    # Exact complete replay catches patch order errors. The frozen portion must still
    # materialize its recorded tree before any renewed patch is considered.
    all_patches = [output / row["file"] for row in rows]
    frozen_tree = staged_tree(source, BASE, all_patches[:18])
    if frozen_tree != FROZEN_TREE:
        raise RuntimeError(f"Frozen replay mismatch: {frozen_tree}")
    resulting_tree = staged_tree(source, BASE, all_patches)

    new_names = [row["file"] for row in rows[18:]]
    for position, filename in enumerate(new_names, 19):
        additional_names = minimal_after_frozen_dependencies(
            source, output, new_names[:position - 19], filename)
        additional_numbers = [new_names.index(name) + 19 for name in additional_names]
        original_numbers, traced_roots = minimal_base_context(
            source, original, frozen["patches"], output, additional_names, filename)
        rows[position - 1]["dependencies"] = original_numbers + additional_numbers
        rows[position - 1]["additional_dependencies_after_frozen_18"] = additional_numbers
        rows[position - 1]["base_context_dependencies"] = original_numbers
        rows[position - 1]["base_context_traced_roots"] = traced_roots
        rows[position - 1]["checked_dependency_order"] = original_numbers + additional_numbers
        rows[position - 1]["dependency_apply_check"] = True
        rows[position - 1]["base_context_apply_check"] = True
        rows[position - 1]["base_context_diff_check"] = True

    # Record every series transition, then compare every packaged source path with
    # the public source head. CI and documentation commits are intentionally absent.
    with tempfile.TemporaryDirectory(prefix="linux-source-package-index-") as directory:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        run(source, "read-tree", BASE, env=env)
        for row in rows:
            row["from_tree"] = run(source, "write-tree", env=env, text=True).strip()
            run(source, "apply", "--cached", "--whitespace=nowarn", output / row["file"], env=env)
            row["to_tree"] = run(source, "write-tree", env=env, text=True).strip()
    added_paths = run(source, "diff", "--name-only", FROZEN_TREE, resulting_tree, text=True).splitlines()
    forbidden_added_paths = [path for path in added_paths if path.startswith((".github/", "doc/"))]
    if forbidden_added_paths:
        raise RuntimeError(f"Renewed patches contain CI/documentation paths: {forbidden_added_paths}")

    files = {}
    for path in changed_paths(source, BASE, all_patches):
        if path.startswith((".github/", "doc/")):
            continue
        packaged = run(source, "show", f"{resulting_tree}:{path}")
        public = run(source, "show", f"{PUBLIC_HEAD}:{path}")
        if packaged != public:
            raise RuntimeError(f"Public-head hash mismatch: {path}")
        files[path] = sha256(packaged)
    public_source_paths = [
        path for path in run(source, "diff", "--name-only", FROZEN_TREE, PUBLIC_HEAD, text=True).splitlines()
        if not path.startswith((".github/", "doc/"))
    ]
    missing_public_source_paths = sorted(set(public_source_paths) - set(files))
    if missing_public_source_paths:
        raise RuntimeError(f"Source package omits public-head paths: {missing_public_source_paths}")

    excluded_public_paths = [
        path for path in run(source, "diff", "--name-only", FROZEN_TREE, PUBLIC_HEAD, text=True).splitlines()
        if path.startswith((".github/", "doc/"))
    ]
    manifest = {
        "schema": 1,
        "base": BASE,
        "frozen_18_tree": FROZEN_TREE,
        "public_source_head": PUBLIC_HEAD,
        "resulting_tree": resulting_tree,
        "patches": rows,
        "files": files,
        "complete_series_replay_passed": True,
        "source_hashes_match_public_head": True,
        "dependency_schema": {
            "dependencies": "Minimal complete patch-number closure when applying from base.",
            "base_context_dependencies": "Minimal frozen-series context required from base.",
            "additional_dependencies_after_frozen_18": "Minimal renewed-patch context required after frozen patch 18.",
        },
        "public_head_source_paths_covered": public_source_paths,
        "public_head_excluded_path_count": len(excluded_public_paths),
        "public_head_excluded_paths_sha256": sha256("\n".join(excluded_public_paths).encode()),
        "scope": "Source-only patch series. No CI or documentation commits are included. Application checks and source identity do not establish build, runtime, compatibility, or performance results.",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    names = [row["file"] for row in rows]
    (output / "series").write_text("\n".join(names) + "\n")
    assert (output / "series").read_text().splitlines() == names
    print(json.dumps({"patches": len(rows), "resulting_tree": resulting_tree, "files": len(files)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    build(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
