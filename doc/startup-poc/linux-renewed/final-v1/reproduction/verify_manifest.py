#!/usr/bin/env python3
"""Verify every payload named by the public final-v1 manifest."""

import gzip
import hashlib
import argparse
import json
from pathlib import Path


def digest(stream):
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        value.update(chunk)
    return value.hexdigest()


def contained(root, relative):
    path = root / relative
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise AssertionError(f"manifest path escapes root: {relative}") from error
    return path


def verify(root):
    assert not root.is_symlink(), 'package root is a symlink'
    root = root.resolve()
    manifest = root / "manifest.json"
    assert not manifest.is_symlink(), 'manifest is a symlink'
    assert not any(path.is_symlink() for path in root.rglob('*')), 'symlink in package'
    entries = json.loads(manifest.read_text())
    assert isinstance(entries, dict) and entries, "manifest must be a nonempty object"
    declared = set()
    for relative, expected in entries.items():
        assert isinstance(relative, str) and isinstance(expected, dict), relative
        relative_path = Path(relative)
        assert not relative_path.is_absolute() and ".." not in relative_path.parts, f"unsafe manifest path: {relative}"
        path = contained(root, relative_path)
        assert path.is_file() and not path.is_symlink(), f"missing manifest payload: {relative}"
        assert path.stat().st_size == expected["bytes"], f"size mismatch: {relative}"
        with path.open("rb") as stream:
            assert digest(stream) == expected["sha256"], f"SHA-256 mismatch: {relative}"
        if "uncompressed_sha256" in expected:
            assert path.suffix == ".gz", f"uncompressed digest on non-gzip payload: {relative}"
            with gzip.open(path, "rb") as stream:
                assert digest(stream) == expected["uncompressed_sha256"], f"uncompressed SHA-256 mismatch: {relative}"
        declared.add(relative_path.as_posix())
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*")
              if path.is_file() and path != manifest}
    assert actual == declared, f"manifest file coverage differs: missing={sorted(actual - declared)}, stale={sorted(declared - actual)}"
    print(f"verified {len(entries)} manifest payloads")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    verify(parser.parse_args().root)
