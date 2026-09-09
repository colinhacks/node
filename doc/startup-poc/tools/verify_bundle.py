#!/usr/bin/env python3
"""Create and audit a self-contained public evidence-bundle manifest.

The manifest is deliberately an inventory, rather than a signature scheme.  It
lets a reviewer detect accidental additions, removals, or byte changes after a
bundle has been assembled, while the content audit prevents known private
material from being packaged in the first place.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote


SCHEMA = 1
DEFAULT_MANIFEST = "PUBLIC-BUNDLE-MANIFEST.json"
CACHE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".tox"}
CACHE_SUFFIXES = {".pyc", ".pyo"}
# Require the first username character to be literal.  This deliberately does
# not match public source that documents a path-matching regex such as
# ``/Users/[^\\s]+`` or ``/home/\\w+``.
HOME_PATH = re.compile(
    r"(?:/(?:Users|home)/(?=[A-Za-z0-9._-])[^\s\"'`]+|"
    r"[A-Za-z]:[\\/]Users[\\/](?=[A-Za-z0-9._-])[^\s\"'`]+)"
)
PRIVATE_KEY = re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----")
SERVICE_ACCOUNT = re.compile(r"[\"']type[\"']\s*:\s*[\"']service_account[\"']", re.I)
CREDENTIAL = re.compile(
    r"(?:\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"aws_access_key_id|aws_secret_access_key|google_application_credentials|"
    r"authorization|x-api-key)\b\s*[=:])",
    re.I,
)
INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\s*\)")
REFERENCE_LINK = re.compile(r"^\s{0,3}\[[^]]+\]:\s*(?:<([^>]+)>|([^\s]+))", re.M)
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


class AuditError(ValueError):
    pass


def fail(message: str) -> None:
    raise AuditError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or any(part in {"", ".", ".."} for part in path.parts):
        fail(f"unsafe manifest name: {value!r}")
    return path


def normalized_manifest_name(value: str) -> PurePosixPath:
    path = safe_relative(value)
    if len(path.parts) != 1:
        fail(f"manifest must be at package root: {value!r}")
    return path


def package_root(value: str) -> Path:
    root = Path(value)
    if root.is_symlink() or not root.is_dir():
        fail("package root must be a non-symlink directory")
    return root.resolve(strict=True)


def relative_path(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        fail(f"path escapes package root: {path}")
    result = relative.as_posix()
    if not result or result.startswith("/") or "\\" in result or any(part in {"", ".", ".."} for part in PurePosixPath(result).parts):
        fail(f"unsafe relative path: {result!r}")
    return result


def reject_cache_or_symlink(root: Path) -> None:
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            candidate = current_path / name
            rel = relative_path(root, candidate)
            if candidate.is_symlink():
                fail(f"symlink is not allowed: {rel}")
            if name in CACHE_PARTS or name.lower().endswith(tuple(CACHE_SUFFIXES)):
                fail(f"cache or bytecode is not allowed: {rel}")
        # Do not descend after reporting a forbidden directory, even if a caller
        # changes this function later to collect multiple errors.
        directories[:] = [name for name in directories if name not in CACHE_PARTS]


def inventory(root: Path, manifest_name: PurePosixPath) -> list[tuple[str, Path]]:
    reject_cache_or_symlink(root)
    files: list[tuple[str, Path]] = []
    for current, _, names in os.walk(root, followlinks=False):
        for name in names:
            path = Path(current) / name
            rel = relative_path(root, path)
            if PurePosixPath(rel) == manifest_name:
                continue
            mode = path.stat(follow_symlinks=False).st_mode
            if not stat.S_ISREG(mode):
                fail(f"non-regular file is not allowed: {rel}")
            files.append((rel, path))
    return sorted(files)


def decoded_text(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def secret_markers(text: str) -> str | None:
    if HOME_PATH.search(text):
        return "home path"
    if PRIVATE_KEY.search(text):
        return "private key material"
    if SERVICE_ACCOUNT.search(text):
        return "service-account JSON"
    if CREDENTIAL.search(text):
        return "cloud credential marker"
    return None


def scan_text(rel: str, data: bytes, *, decompressed: bool = False) -> None:
    text = decoded_text(data)
    if text is None:
        return
    marker = secret_markers(text)
    if marker:
        source = "decompressed " if decompressed else ""
        fail(f"{source}{marker} found in {rel}")


def gzip_details(rel: str, data: bytes) -> tuple[str, int]:
    try:
        decoded = gzip.decompress(data)
    except (OSError, EOFError) as error:
        fail(f"invalid gzip file {rel}: {error}")
    scan_text(rel, decoded, decompressed=True)
    return sha256(decoded), len(decoded)


def link_targets(markdown: str) -> list[str]:
    values = []
    for match in [*INLINE_LINK.finditer(markdown), *REFERENCE_LINK.finditer(markdown)]:
        values.append(match.group(1) or match.group(2))
    return values


def check_markdown_links(root: Path, rel: str, data: bytes) -> None:
    if Path(rel).suffix.lower() not in {".md", ".mdx"}:
        return
    markdown = decoded_text(data)
    if markdown is None:
        fail(f"Markdown is not UTF-8: {rel}")
    for target in link_targets(markdown):
        target = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not target or target.startswith("#") or SCHEME.match(target):
            continue
        # A leading slash is bundle-root-relative; other local links are
        # relative to the Markdown file that contains them.
        candidate = root / target.lstrip("/") if target.startswith("/") else (root / rel).parent / target
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            fail(f"local Markdown link escapes package: {rel} -> {target}")
        if not resolved.exists():
            fail(f"missing local Markdown link: {rel} -> {target}")


def collect_entries(root: Path, manifest_name: PurePosixPath) -> list[dict[str, object]]:
    entries = []
    for rel, path in inventory(root, manifest_name):
        data = path.read_bytes()
        scan_text(rel, data)
        check_markdown_links(root, rel, data)
        entry: dict[str, object] = {"path": rel, "sha256": sha256(data), "bytes": len(data)}
        if rel.lower().endswith(".gz"):
            decoded_sha, decoded_bytes = gzip_details(rel, data)
            entry.update(decompressed_sha256=decoded_sha, decompressed_bytes=decoded_bytes)
        entries.append(entry)
    return entries


def create(package: str, manifest: str) -> None:
    root = package_root(package)
    manifest_name = normalized_manifest_name(manifest)
    entries = collect_entries(root, manifest_name)
    target = root / manifest_name
    if target.exists() and target.is_symlink():
        fail(f"manifest is a symlink: {manifest}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_json({"schema": SCHEMA, "files": entries}))
    print(json.dumps({"files": len(entries), "manifest": str(target)}, sort_keys=True))


def manifest_entries(value: object) -> list[dict[str, object]]:
    if not isinstance(value, dict) or set(value) != {"schema", "files"} or value.get("schema") != SCHEMA:
        fail("unsupported manifest schema")
    entries = value["files"]
    if not isinstance(entries, list):
        fail("manifest files must be a list")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) not in ({"path", "sha256", "bytes"}, {"path", "sha256", "bytes", "decompressed_sha256", "decompressed_bytes"}):
            fail("malformed manifest entry")
        rel, digest, size = entry.get("path"), entry.get("sha256"), entry.get("bytes")
        if not isinstance(rel, str) or not safe_relative(rel) or rel in seen:
            fail("unsafe or duplicate manifest path")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or not isinstance(size, int) or size < 0:
            fail(f"malformed manifest digest or size: {rel}")
        gz = "decompressed_sha256" in entry
        if gz != ("decompressed_bytes" in entry):
            fail(f"incomplete decompressed record: {rel}")
        if gz and (not rel.lower().endswith(".gz") or not isinstance(entry["decompressed_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["decompressed_sha256"]) or not isinstance(entry["decompressed_bytes"], int) or entry["decompressed_bytes"] < 0):
            fail(f"malformed decompressed record: {rel}")
        seen.add(rel)
    return entries


def verify(package: str, manifest: str) -> None:
    root = package_root(package)
    manifest_name = normalized_manifest_name(manifest)
    manifest_path = root / manifest_name
    if manifest_path.is_symlink() or not manifest_path.is_file():
        fail(f"missing regular manifest: {manifest}")
    raw_manifest = manifest_path.read_bytes()
    scan_text(manifest, raw_manifest)
    try:
        expected = manifest_entries(json.loads(raw_manifest))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"invalid manifest JSON: {error}")
    actual = collect_entries(root, manifest_name)
    if [item["path"] for item in expected] != [item["path"] for item in actual]:
        fail("package file set differs from manifest")
    if expected != actual:
        fail("package file content differs from manifest")
    print(json.dumps({"files_verified": len(actual), "manifest": str(manifest_path)}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--package", required=True)
        command.add_argument("--manifest", default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    try:
        if args.command == "create":
            create(args.package, args.manifest)
        else:
            verify(args.package, args.manifest)
    except (AuditError, OSError) as error:
        print(f"public-bundle: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
