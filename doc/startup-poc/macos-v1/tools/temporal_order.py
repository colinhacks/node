#!/usr/bin/env python3
"""Map actual temporal-profile order to exact final Mach-O text atoms."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

from startup_order import input_record, parse_nm_text, sha256_file


TRACE_HEADER = re.compile(r"Temporal Profile Traces \(samples=(\d+) seen=(\d+)\)")


def map_temporal_order(raw, symbols):
    entries = []
    for number, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if any(character.isspace() for character in line) or any(
                character in line for character in ("#", ":", "\0")):
            raise ValueError(f"invalid order symbol on line {number}: {line!r}")
        entries.append((number, line))
    if not entries:
        raise ValueError("temporal order contains no symbols")
    frequencies = Counter(name for _, name in entries)
    by_name = {}
    for symbol in symbols:
        by_name.setdefault(symbol.emitted_name, []).append(symbol)
    seen_addresses = set()
    accepted = {}
    audit = []
    for number, name in entries:
        matches = by_name.get("_" + name, [])
        record = dict(line=number, profile_name=name, emitted_symbol=None,
                      address=None)
        if frequencies[name] != 1:
            reason = "duplicate-profile-name"
        elif not matches:
            reason = "missing-text-symbol"
        elif len(matches) != 1:
            reason = "symbol-collision"
        else:
            symbol = matches[0]
            record.update(emitted_symbol=symbol.emitted_name,
                          address=symbol.address)
            if symbol.address in seen_addresses:
                reason = "alias-address"
            else:
                reason = "accepted"
                seen_addresses.add(symbol.address)
                accepted[number] = symbol.emitted_name
        audit.append(dict(**record, disposition=reason))
    output = []
    for number, line in enumerate(raw.splitlines(), 1):
        if line.lstrip().startswith("#"):
            output.append(line)
        elif number in accepted:
            output.append(accepted[number])
    return "\n".join(output) + "\n", audit


def temporal_counts(text):
    match = TRACE_HEADER.search(text)
    if not match or not all(int(value) > 0 for value in match.groups()):
        raise ValueError("profile has no nonzero temporal traces")
    return dict(samples=int(match[1]), seen=int(match[2]))


def create_temporal_order(profile, binary, tool, nm, output):
    paths = [Path(path).resolve(strict=True) for path in (profile, binary, tool, nm)]
    profile, binary, tool, nm = paths
    if any(not path.is_file() for path in paths):
        raise ValueError("profile, binary and tools must be regular files")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    commands = []

    def run(argv, name):
        with (output / name).open("x") as stream:
            result = subprocess.run(list(map(str, argv)), stdout=stream,
                                    stderr=subprocess.PIPE, text=True, timeout=120)
        commands.append(dict(argv=list(map(str, argv)), exit=result.returncode,
                             stderr=result.stderr, stdout=name))
        (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        result.check_returncode()

    run([tool, "show", "--temporal-profile-traces", profile], "traces.txt")
    # Only the header is needed in memory; the full evidence remains on disk.
    with (output / "traces.txt").open() as stream:
        header = next((line for line in stream if TRACE_HEADER.search(line)), "")
    counts = temporal_counts(header)
    run([tool, "order", profile, "--output", output / "raw.order"], "order.log")
    run([nm, "-n", "-arch", "arm64", binary], "symbols.nm")
    raw = (output / "raw.order").read_text()
    symbols = parse_nm_text((output / "symbols.nm").read_text())
    order, audit = map_temporal_order(raw, symbols)
    if not any(row["disposition"] == "accepted" for row in audit):
        raise ValueError("temporal profile matched no unique final-image text atoms")
    provenance = dict(profile=input_record(profile), binary=input_record(binary),
                      llvm_profdata=input_record(tool), nm=input_record(nm))
    header = ("# Exact temporal order; no counter ranking or fuzzy matching.\n"
              f"# binary_sha256={provenance['binary']['sha256']}\n"
              f"# profile_sha256={provenance['profile']['sha256']}\n")
    (output / "startup-temporal.order").write_text(header + order)
    (output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    report = dict(inputs=provenance, temporal_counts=counts, commands=commands,
                  counts=dict(Counter(row["disposition"] for row in audit)),
                  order_sha256=sha256_file(output / "startup-temporal.order"),
                  mapper_sha256=sha256_file(__file__),
                  algorithm="Preserve order; prepend exactly one Mach-O underscore; "
                  "omit duplicate profile names, ambiguous text symbols and aliases")
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("profile", "binary", "llvm-profdata", "nm", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    report = create_temporal_order(args.profile, args.binary, args.llvm_profdata,
                                   args.nm, args.output)
    print(json.dumps({key: report[key] for key in ("temporal_counts", "counts")}))


if __name__ == "__main__":
    main()
