#!/usr/bin/env python3
"""Record build-time source/configuration separately from later benchmark state."""

import argparse
import datetime
import json
from pathlib import Path
import shutil
import subprocess

from startup_lab import prepare_output, sanitized_environment, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-command", required=True)
    parser.add_argument("--note", action="append", default=[])
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    binary = args.binary.resolve(strict=True)
    config = args.config.resolve(strict=True)
    output = prepare_output(args.output)

    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(source), *arguments])

    patch = git("diff", "--binary", "HEAD")
    (output / "source.patch").write_bytes(patch)
    shutil.copyfile(config, output / "config.gypi")
    untracked = []
    for raw in git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode())
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Unsupported untracked source file: {path}")
        path.resolve().relative_to(source)
        destination = output / "untracked" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        untracked.append({"path": str(relative), "sha256": sha256(str(path))})

    environment, _ = sanitized_environment()
    manifest = {
        "schema": 1,
        "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "binary": str(binary), "binary_sha256": sha256(str(binary)),
        "binary_bytes": binary.stat().st_size,
        "version": subprocess.check_output([str(binary), "--version"],
                                           env=environment, text=True).strip(),
        "source": str(source), "head": git("rev-parse", "HEAD").decode().strip(),
        "status": git("status", "--porcelain=v1").decode(),
        "source_patch_sha256": sha256(str(output / "source.patch")),
        "untracked": untracked, "config_sha256": sha256(str(output / "config.gypi")),
        "build_command": args.build_command, "notes": args.note,
    }
    # The generated file records the actual compiler and linker flags, including
    # environment additions which configure's JSON does not always retain.
    ninja = source / "out/Release/obj/node.ninja"
    if ninja.exists():
        shutil.copyfile(ninja, output / "node.ninja")
        manifest["node_ninja_sha256"] = sha256(str(output / "node.ninja"))
    for relative, name in (
        ("build.ninja", "build.ninja"),
        ("obj/tools/v8_gypfiles/v8_base_without_compiler.ninja", "v8_base.ninja"),
    ):
        generated = source / "out/Release" / relative
        if generated.exists():
            shutil.copyfile(generated, output / name)
            manifest[name.replace(".", "_") + "_sha256"] = sha256(str(output / name))
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(output / "manifest.json")


if __name__ == "__main__":
    main()
