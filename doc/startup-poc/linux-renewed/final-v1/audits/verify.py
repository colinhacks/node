#!/usr/bin/env python3
"""Independent, index-only verification of source-package-v1."""

import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "worktrees/public-startup"
PACKAGE = ROOT / "startup-lab/platform/linux-renewed/source-package-v1"
ORIGINAL = ROOT / "startup-lab/public-platform-pr/patches"
OUT = Path(__file__).with_name("evidence.json")
BASE = "8af75451e9041cd6058080ad3d4a65546797b418"
FROZEN = "3166f9876aa2586b4008f7c722ba406e8258d44a"
HEAD = "f788616cf1515e30a8cce13513dbe8b30e567904"


def git(*args, env=None, text=True, check=True):
    return subprocess.run(
        ["git", "-C", str(SOURCE), *map(str, args)], env=env, text=text,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths(path):
    return set(re.findall(r"^diff --git a/(.*?) b/", path.read_text(errors="replace"), re.M))


def closure(numbers, rows):
    answer, pending = set(numbers), list(numbers)
    while pending:
        for dep in rows[pending.pop() - 1]["dependencies"]:
            if dep not in answer:
                answer.add(dep)
                pending.append(dep)
    return tuple(sorted(answer))


def apply_tree(base, patch_names):
    with tempfile.TemporaryDirectory(prefix="source-package-audit-index-") as td:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(td) / "index"))
        git("read-tree", base, env=env)
        for name in patch_names:
            result = git("apply", "--cached", "--whitespace=nowarn", PACKAGE / name,
                         env=env, check=False)
            if result.returncode:
                return None, result.stderr
        check = git("diff", "--cached", "--check", env=env, check=False)
        if check.returncode:
            return None, check.stderr
        return git("write-tree", env=env).stdout.strip(), ""


def apply_with_original(base, original_numbers, additional_names, candidate):
    with tempfile.TemporaryDirectory(prefix="source-package-audit-index-") as td:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(td) / "index"))
        git("read-tree", base, env=env)
        for number in original_numbers:
            result = git("apply", "--cached", "--whitespace=nowarn",
                         ORIGINAL / original_rows[number - 1]["file"], env=env, check=False)
            if result.returncode:
                return False
        for name in additional_names + [candidate]:
            result = git("apply", "--cached", "--whitespace=nowarn", PACKAGE / name,
                         env=env, check=False)
            if result.returncode:
                return False
        return not git("diff", "--cached", "--check", env=env, check=False).returncode


manifest = json.loads((PACKAGE / "manifest.json").read_text())
original_manifest = json.loads((ORIGINAL / "manifest.json").read_text())
original_rows = original_manifest["patches"]
series_raw = (PACKAGE / "series").read_text()
expected_series = [row["file"] for row in manifest["patches"]]
# Continue independent artifact validation from the manifest's enumerated patch files,
# even when the optional series file itself is malformed.
series = expected_series
result = {"head": git("rev-parse", "HEAD").stdout.strip(), "checks": {}}

result["checks"]["constants"] = {
    "pass": (manifest["base"], manifest["frozen_18_tree"], manifest["public_source_head"])
    == (BASE, FROZEN, HEAD) and result["head"] == HEAD,
    "observed": [manifest["base"], manifest["frozen_18_tree"], manifest["public_source_head"], result["head"]],
}

frozen = []
for row in original_rows:
    filename = row["file"]
    frozen.append({"file": filename, "original": digest(ORIGINAL / filename),
                   "package": digest(PACKAGE / filename), "manifest": row["sha256"]})
result["checks"]["frozen_bytes"] = {
    "pass": len(frozen) == 18 and all(x["original"] == x["package"] == x["manifest"] for x in frozen),
    "patches": frozen,
}
result["checks"]["series"] = {
    "pass": series_raw == "".join(f"{name}\n" for name in expected_series),
    "expected": expected_series,
    "observed_repr": repr(series_raw),
}
package_digests = [{"file": row["file"], "actual": digest(PACKAGE / row["file"]),
                    "manifest": row["sha256"]} for row in manifest["patches"]]
result["checks"]["package_digests"] = {
    "pass": all(item["actual"] == item["manifest"] for item in package_digests),
    "patches": package_digests,
}

tree, error = apply_tree(BASE, series)
result["checks"]["full_replay"] = {"pass": tree == manifest["resulting_tree"], "tree": tree, "error": error}
frozen_tree, error = apply_tree(BASE, series[:18])
result["checks"]["frozen_replay"] = {"pass": frozen_tree == FROZEN, "tree": frozen_tree, "error": error}

with tempfile.TemporaryDirectory(prefix="source-package-audit-index-") as td:
    env = dict(os.environ, GIT_INDEX_FILE=str(Path(td) / "index"))
    git("read-tree", BASE, env=env)
    transitions = []
    for name in series:
        before = git("write-tree", env=env).stdout.strip()
        git("apply", "--cached", "--whitespace=nowarn", PACKAGE / name, env=env)
        after = git("write-tree", env=env).stdout.strip()
        transitions.append({"file": name, "from": before, "to": after})
result["checks"]["transitions"] = {
    "pass": all(t["from"] == row["from_tree"] and t["to"] == row["to_tree"]
                for t, row in zip(transitions, manifest["patches"])),
    "observed": transitions,
}

changed = git("diff", "--name-only", BASE, manifest["resulting_tree"]).stdout.splitlines()
mapping = []
for path in changed:
    packaged = git("show", f"{manifest['resulting_tree']}:{path}", text=False).stdout
    public = git("show", f"{HEAD}:{path}", text=False).stdout
    mapping.append({"path": path, "sha256": hashlib.sha256(packaged).hexdigest(),
                    "public_matches": packaged == public})
manifest_files = manifest["files"]
result["checks"]["source_mapping"] = {
    "pass": set(changed) == set(manifest_files) and all(x["public_matches"] and manifest_files[x["path"]] == x["sha256"] for x in mapping),
    "changed_count": len(changed), "manifest_count": len(manifest_files), "files": mapping,
    "non_source_head_differences": [p for p in git("diff", "--name-only", manifest["resulting_tree"], HEAD).stdout.splitlines() if not p.startswith((".github/", "doc/"))],
    "all_head_differences": git("diff", "--name-only", manifest["resulting_tree"], HEAD).stdout.splitlines(),
}
renewed_paths = git("diff", "--name-only", FROZEN, manifest["resulting_tree"]).stdout.splitlines()
result["checks"]["renewed_scope"] = {
    "pass": not [p for p in renewed_paths if p.startswith((".github/", "doc/"))],
    "paths": renewed_paths,
}

new_names = series[18:]
dependency_audit = {}
for position, name in enumerate(new_names, start=19):
    row = manifest["patches"][position - 1]
    candidate_paths = paths(PACKAGE / name)
    roots = [n for n, old in enumerate(original_rows, start=1)
             if candidate_paths & paths(ORIGINAL / old["file"])]
    additional = row["additional_dependencies_after_frozen_18"]
    additional_names = [series[n - 1] for n in additional]
    feasible = set()
    for subset_size in range(len(roots) + 1):
        for subset in itertools.combinations(roots, subset_size):
            candidate_closure = closure(subset, original_rows)
            if apply_with_original(BASE, candidate_closure, additional_names, name):
                feasible.add(candidate_closure)
    minimum_size = min(map(len, feasible)) if feasible else None
    minima = sorted(x for x in feasible if len(x) == minimum_size)

    # The separate after-frozen-18 claim is audited by enumerating every preceding renewed subset.
    prefix = new_names[:position - 19]
    after_frozen = []
    for subset_size in range(len(prefix) + 1):
        for subset in itertools.combinations(prefix, subset_size):
            okay, _ = apply_tree(FROZEN, list(subset) + [name])
            if okay is not None:
                after_frozen.append(list(subset))
    after_min = min(map(len, after_frozen)) if after_frozen else None
    after_minima = sorted(x for x in after_frozen if len(x) == after_min)
    expected_base = tuple(row["base_context_dependencies"])
    expected_after = additional_names
    dependency_audit[name] = {
        "roots": roots,
        "base_feasible_closures": [list(x) for x in sorted(feasible)],
        "base_minimum_closures": [list(x) for x in minima],
        "declared_base_closure": list(expected_base),
        "base_pass": expected_base in minima,
        "after_frozen_minimum_subsets": after_minima,
        "declared_after_frozen_subset": expected_after,
        "after_frozen_pass": expected_after in after_minima,
    }
result["checks"]["dependency_closures"] = {
    "pass": all(v["base_pass"] and v["after_frozen_pass"] for v in dependency_audit.values()),
    "patches": dependency_audit,
}

OUT.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"pass": all(c.get("pass", True) for c in result["checks"].values()), "evidence": str(OUT)}))
