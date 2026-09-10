#!/usr/bin/env python3
"""Capture ELF relocation pressure and glibc loader statistics for Node binaries.

This is an observation tool.  It never changes the supplied executable or its
environment outside the child process.  On Linux, omit ``--static-only`` to
also record ``LD_DEBUG=statistics`` for each requested launch command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys


RELATIVE = "R_X86_64_RELATIVE"


def sha256(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as source:
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest()


def command_output(command: list[str], timeout: float) -> str:
  return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT,
                                 timeout=timeout)


def dynamic_tags(readelf: str, binary: Path, timeout: float) -> dict[str, int]:
  tags: dict[str, int] = {}
  for line in command_output([readelf, "-dW", str(binary)], timeout).splitlines():
    match = re.search(r"\(([^)]+)\)\s+(.+)$", line)
    if not match:
      continue
    key, value = match.groups()
    number = re.search(r"\b([0-9]+)\s+\(bytes\)|\b0x([0-9a-fA-F]+)|\b([0-9]+)\b", value)
    if number:
      decimal = number.group(1) or number.group(3)
      tags[key] = int(decimal or number.group(2), 10 if decimal else 16)
  return tags


def relocation_offsets(readelf: str, binary: Path, timeout: float) -> list[int]:
  offsets = []
  for line in command_output([readelf, "-rW", str(binary)], timeout).splitlines():
    match = re.match(r"^([0-9a-fA-F]+)\s+\S+\s+" + RELATIVE + r"\b", line)
    if match:
      offsets.append(int(match.group(1), 16))
  return sorted(offsets)


def relr_word_count(offsets: list[int]) -> int:
  """Return the greedy x86-64 RELR encoding size in eight-byte words.

  A direct address starts each run.  A following bitmap word describes the next
  63 pointer-sized slots.  This is an encoding-size estimate, not proof that a
  particular linker will emit the same ordering.
  """
  words = 0
  index = 0
  while index < len(offsets):
    words += 1
    cursor = offsets[index] + 8
    index += 1
    while index < len(offsets) and offsets[index] <= cursor + 62 * 8:
      words += 1
      limit = cursor + 62 * 8
      while index < len(offsets) and offsets[index] <= limit:
        index += 1
      cursor += 63 * 8
  return words


def static_record(readelf: str, binary: Path, timeout: float) -> dict[str, object]:
  offsets = relocation_offsets(readelf, binary, timeout)
  tags = dynamic_tags(readelf, binary, timeout)
  relr_words = relr_word_count(offsets)
  rela_bytes = len(offsets) * 24
  packed_bytes = tags.get("RELRSZ", 0)
  return {
      "relative_rela": {"count": len(offsets), "bytes": rela_bytes},
      "actual_relr_packed_table": {
          "present": "RELRSZ" in tags or "RELR" in tags,
          "address": tags.get("RELR"),
          "bytes": packed_bytes,
          "pointer_words": packed_bytes // 8,
      },
      "estimated_relr_from_rela": None if not offsets else {
          "bytes": relr_words * 8,
          "pointer_words": relr_words,
          "reduction": 1 - (relr_words * 8 / rela_bytes),
      },
      "dynamic_tags": {key: tags[key] for key in ("RELASZ", "RELACOUNT", "RELRSZ", "RELR") if key in tags},
  }


def diagnostic_environment() -> tuple[dict[str, str], list[str]]:
  environment = dict(os.environ)
  removed = sorted(key for key in environment
                   if key.startswith(("NODE_", "__NUB_", "LD_")))
  for key in removed:
    environment.pop(key)
  environment["LD_DEBUG"] = "statistics"
  return environment, removed


def timeout_text(value: str | bytes | None) -> str:
  if isinstance(value, bytes):
    return value.decode(errors="replace")
  return value or ""


def loader_statistics(binary: Path, arguments: list[str], timeout: float) -> dict[str, object]:
  environment, removed = diagnostic_environment()
  try:
    result = subprocess.run([str(binary), *arguments], text=True, capture_output=True,
                            env=environment, check=False, timeout=timeout)
  except subprocess.TimeoutExpired as error:
    return {"timed_out": True, "timeout_seconds": timeout,
            "statistics_lines": [], "stderr": timeout_text(error.stderr),
            "stdout": timeout_text(error.stdout),
            "environment": {"removed_keys": removed, "set": {"LD_DEBUG": "statistics"}}}
  # glibc writes loader statistics to stderr. Keep the exact text because its
  # labels and availability vary by glibc release.
  lines = [line for line in result.stderr.splitlines() if "total startup time" in line or
           "time needed for relocation" in line or "number of relocations" in line]
  return {"timed_out": False, "timeout_seconds": timeout, "returncode": result.returncode,
          "statistics_lines": lines, "stderr": result.stderr, "stdout": result.stdout,
          "environment": {"removed_keys": removed, "set": {"LD_DEBUG": "statistics"}}}


def parse_options(arguments: list[str] | None = None) -> argparse.Namespace:
  raw_arguments = list(sys.argv[1:] if arguments is None else arguments)
  if "--" in raw_arguments:
    separator = raw_arguments.index("--")
    probe_arguments, command = raw_arguments[:separator], raw_arguments[separator + 1:]
  else:
    probe_arguments, command = raw_arguments, []
  parser = argparse.ArgumentParser()
  parser.add_argument("binary", type=Path)
  parser.add_argument("--readelf", default="readelf")
  parser.add_argument("--output", required=True, type=Path)
  parser.add_argument("--timeout", type=float, default=30.0)
  parser.add_argument("--static-only", action="store_true")
  options = parser.parse_args(probe_arguments)
  if options.timeout <= 0:
    parser.error("--timeout must be positive")
  options.command = command
  return options


def main() -> None:
  options = parse_options()
  if options.output.exists():
    raise SystemExit(f"refusing to overwrite {options.output}")
  if not options.binary.is_file():
    raise SystemExit(f"not a file: {options.binary}")
  record: dict[str, object] = {"schema": 2, "binary": {"path": str(options.binary),
      "sha256": sha256(options.binary), "bytes": options.binary.stat().st_size},
      "static": static_record(options.readelf, options.binary, options.timeout)}
  if not options.static_only:
    if platform.system() != "Linux":
      raise SystemExit("loader statistics require Linux; use --static-only elsewhere")
    record["loader_statistics"] = loader_statistics(options.binary, options.command, options.timeout)
  options.output.parent.mkdir(parents=True, exist_ok=True)
  options.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
  main()
