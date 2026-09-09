#!/usr/bin/env python3
"""Create auditable Darwin linker order files from an IR PGO profile.

This tool ranks final-image text symbols by profile block hotness.  It does
not claim to recover a temporal execution order.
"""

import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


FUNCTION_HEADER = re.compile(r"^  (.+):$")
BLOCK_COUNTS = re.compile(r"^    Block counts: \[([^]]*)\]$")
NM_TEXT = re.compile(r"^\s*([0-9A-Fa-f]+)\s+([tT])\s+(\S+)\s*$")


@dataclass(frozen=True)
class ProfileFunction:
    name: str
    score: int

    @property
    def source_qualifier(self):
        return self.name.rsplit(";", 1)[0] if ";" in self.name else ""

    @property
    def base_name(self):
        return self.name.rsplit(";", 1)[-1]


@dataclass(frozen=True)
class TextSymbol:
    address: int
    emitted_name: str

    @property
    def normalized_name(self):
        # Mach-O nm prefixes its external spelling with exactly one underscore.
        return self.emitted_name[1:] if self.emitted_name.startswith("_") else self.emitted_name


@dataclass(frozen=True)
class Match:
    profile_name: str
    source_qualifier: str
    score: int
    address: int
    emitted_symbol: str
    rank: int = 0


@dataclass(frozen=True)
class Omission:
    profile_name: str
    source_qualifier: str
    score: int
    reason: str
    detail: str = ""


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_profdata_show(text):
    """Parse the stable text form of `llvm-profdata show --all-functions --counts`."""
    functions = []
    current_name = None
    for line in text.splitlines():
        header = FUNCTION_HEADER.match(line)
        if header:
            current_name = header.group(1)
            continue
        counts = BLOCK_COUNTS.match(line)
        if counts and current_name is not None:
            values = [int(value.strip()) for value in counts.group(1).split(",")
                      if value.strip()]
            functions.append(ProfileFunction(current_name, max(values, default=0)))
            current_name = None
    if not functions:
        raise ValueError("llvm-profdata output contained no function block counts")
    return functions


def parse_nm_text(text):
    """Keep only defined arm64 text atoms from `nm -n -arch arm64`."""
    symbols = []
    for line in text.splitlines():
        match = NM_TEXT.match(line)
        if match:
            symbols.append(TextSymbol(int(match.group(1), 16), match.group(3)))
    if not symbols:
        raise ValueError("nm output contained no defined text symbols")
    return symbols


def map_functions(functions, symbols):
    """Return exact, unique profile-to-final-image matches and all omissions."""
    by_name = {}
    for symbol in symbols:
        by_name.setdefault(symbol.normalized_name, []).append(symbol)

    candidates = []
    omissions = []
    for function in functions:
        if function.score <= 0:
            omissions.append(Omission(function.name, function.source_qualifier,
                                      function.score, "zero-score"))
            continue
        matching = by_name.get(function.base_name, [])
        if not matching:
            omissions.append(Omission(function.name, function.source_qualifier,
                                      function.score, "missing-symbol",
                                      function.base_name))
        elif len(matching) != 1:
            omissions.append(Omission(function.name, function.source_qualifier,
                                      function.score, "symbol-collision",
                                      ",".join(item.emitted_name for item in matching)))
        else:
            candidates.append((function, matching[0]))

    # The final image can expose aliases at an identical address.  Never put
    # more than one spelling for that atom in an order file.
    accepted = []
    seen_addresses = set()
    for function, symbol in sorted(candidates,
                                   key=lambda item: (-item[0].score,
                                                     item[1].address,
                                                     item[1].emitted_name,
                                                     item[0].name)):
        if symbol.address in seen_addresses:
            omissions.append(Omission(function.name, function.source_qualifier,
                                      function.score, "alias-address",
                                      symbol.emitted_name))
            continue
        seen_addresses.add(symbol.address)
        accepted.append(Match(function.name, function.source_qualifier,
                              function.score, symbol.address, symbol.emitted_name))

    matches = [Match(**{**asdict(match), "rank": index})
               for index, match in enumerate(accepted, start=1)]
    return matches, sorted(omissions, key=lambda item: (item.reason, item.profile_name))


def run_command(command):
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("command failed (%d): %s\n%s" %
                           (result.returncode, " ".join(command), result.stderr))
    return result.stdout


def write_tsv(path, rows, fields):
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t",
                                lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


def write_order_file(path, matches, cutoff, provenance):
    selected = matches[:cutoff]
    lines = [
        "# Generated by startup-lab/startup_order.py; do not hand-edit.",
        "# binary_sha256=%s" % provenance["inputs"]["binary"]["sha256"],
        "# profile_sha256=%s" % provenance["inputs"]["profile"]["sha256"],
        "# cutoff=%d selected=%d" % (cutoff, len(selected)),
        "# Ranked by maximum IR PGO block count, not temporal execution order.",
    ]
    lines.extend(match.emitted_symbol for match in selected)
    path.write_text("\n".join(lines) + "\n")
    return {"path": str(path), "requested": cutoff, "selected": len(selected),
            "sha256": sha256_file(path)}


def input_record(path):
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": sha256_file(path)}


def create_order_artifacts(profile, binary, llvm_profdata, nm, output):
    profile = Path(profile).resolve(strict=True)
    binary = Path(binary).resolve(strict=True)
    llvm_profdata = Path(llvm_profdata).resolve(strict=True)
    nm = Path(nm).resolve(strict=True)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("refusing to overwrite existing output directory: %s" % output)
    if not profile.is_file() or not binary.is_file() or not llvm_profdata.is_file() or not nm.is_file():
        raise ValueError("profile, binary, llvm-profdata, and nm must be regular files")

    profdata_command = [str(llvm_profdata), "show", "--all-functions", "--counts", str(profile)]
    nm_command = [str(nm), "-n", "-arch", "arm64", str(binary)]
    functions = parse_profdata_show(run_command(profdata_command))
    symbols = parse_nm_text(run_command(nm_command))
    matches, omissions = map_functions(functions, symbols)

    provenance = {
        "inputs": {"profile": input_record(profile), "binary": input_record(binary)},
        "tools": {"llvm_profdata": input_record(llvm_profdata), "nm": input_record(nm)},
        "commands": {"llvm_profdata_show": profdata_command, "nm": nm_command},
        "algorithm": {
            "profile_score": "maximum block count",
            "symbol_mapping": "exact Mach-O normalized spelling only",
            "temporal_inference": "not attempted; IR counter profiles do not encode a call sequence",
        },
    }
    temporary = Path(tempfile.mkdtemp(prefix=output.name + ".", dir=output.parent))
    try:
        write_tsv(temporary / "matches.tsv", matches,
                  ["rank", "profile_name", "source_qualifier", "score", "address", "emitted_symbol"])
        write_tsv(temporary / "omissions.tsv", omissions,
                  ["profile_name", "source_qualifier", "score", "reason", "detail"])
        orders = {str(cutoff): write_order_file(temporary / ("startup-order-%d.txt" % cutoff),
                                                matches, cutoff, provenance)
                  for cutoff in (64, 256, 1024)}
        # The directory is atomically renamed below; never leak its temporary
        # provenance path into the durable manifest.
        for order in orders.values():
            order["path"] = str(output / Path(order["path"]).name)
        report = {**provenance,
                  "counts": {"profile_functions": len(functions), "text_symbols": len(symbols),
                             "matches": len(matches), "omissions": len(omissions)},
                  "orders": orders,
                  "match_sha256": sha256_file(temporary / "matches.tsv"),
                  "omission_sha256": sha256_file(temporary / "omissions.tsv")}
        (temporary / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        temporary.replace(output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--llvm-profdata", required=True, type=Path)
    parser.add_argument("--nm", default="/usr/bin/nm", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = create_order_artifacts(args.profile, args.binary, args.llvm_profdata,
                                    args.nm, args.output)
    print(json.dumps({"output": str(args.output), "counts": report["counts"],
                      "orders": report["orders"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
