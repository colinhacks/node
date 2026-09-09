#!/usr/bin/env python3
"""Compare defined default-visibility ELF dynamic symbols from readelf dumps."""

from __future__ import annotations

import argparse
import collections
import re
from pathlib import Path


RECORD = re.compile(
    r"^\s*\d+:\s+\S+\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*(.*)$"
)


def symbols(path: Path) -> dict[str, tuple[str, str, str]]:
    result = {}
    for line in path.read_text().splitlines():
        match = RECORD.match(line)
        if match is None:
            continue
        size, kind, bind, visibility, section, name = match.groups()
        if section != "UND" and bind in {"GLOBAL", "WEAK"} and visibility == "DEFAULT" and name:
            result[name] = (kind, bind, size)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    baseline = symbols(args.baseline)
    candidate = symbols(args.candidate)
    removed = {name: baseline[name] for name in baseline.keys() - candidate.keys()}
    added = {name: candidate[name] for name in candidate.keys() - baseline.keys()}
    print(f"baseline defined default exports: {len(baseline)}")
    print(f"candidate defined default exports: {len(candidate)}")
    print(f"removed: {len(removed)}")
    print(f"added: {len(added)}")
    print("removed by type/binding:")
    for key, count in sorted(collections.Counter((kind, bind) for kind, bind, _ in removed.values()).items()):
        print(f"  {key[0]} {key[1]}: {count}")
    print("removed public-C prefixes:")
    for prefix in ("napi_", "node_api_", "node_"):
        print(f"  {prefix}: {sum(name.startswith(prefix) for name in removed)}")
    print("removed mangled implementation prefixes:")
    prefixes = {
        "node namespace": ("_ZN4node", "_ZNK4node", "_ZTVN4node", "_ZTIN4node", "_ZTSN4node"),
        "v8 namespace": ("_ZN2v8", "_ZNK2v8", "_ZTVN2v8", "_ZTIN2v8", "_ZTSN2v8"),
        "v8 inspector": ("_ZN12v8_inspector",),
        "icu": ("_ZN3icu", "_ZNK3icu", "_ZN6icu", "_ZNK6icu"),
        "ada": ("_ZN3ada", "_ZNK3ada"),
        "simdjson": ("_ZN8simdjson", "_ZNK8simdjson"),
    }
    for label, prefixes in prefixes.items():
        print(f"  {label}: {sum(name.startswith(prefixes) for name in removed)}")


if __name__ == "__main__":
    main()
