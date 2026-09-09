#!/usr/bin/env python3
"""Verify published evidence hashes and recompute statistics from retained samples."""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

from startup_lab import paired_ratio, summary


ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(actual, expected):
    if isinstance(expected, (float, int)):
        return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
    return actual == expected


def verify(bootstrap=False):
    manifest = json.loads((ROOT / "MANIFEST.json").read_text())
    for entry in manifest["files"]:
        path = ROOT / entry["path"]
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == entry["published_sha256"],
                f"published hash mismatch: {entry['path']}")
        decoded = gzip.decompress(data) if path.suffix == ".gz" else data
        require(hashlib.sha256(decoded).hexdigest() == entry["decoded_sha256"],
                f"decoded hash mismatch: {entry['path']}")

    experiments = json.loads((ROOT / "evidence/index.json").read_text())
    samples = comparisons = 0
    for experiment in experiments:
        name = experiment["name"]
        report = json.loads(gzip.decompress(
            (ROOT / "evidence" / experiment["report"]).read_bytes()))
        records = [json.loads(line) for line in gzip.decompress(
            (ROOT / "evidence" / experiment["raw"]).read_bytes()).splitlines()]
        samples += len(records)
        measured = [row for row in records
                    if row["phase"] == "measured" and row["status"] == "ok"]
        failures = sum(row["status"] != "ok" for row in records)
        for workload, metrics in report["summaries"].items():
            for metric, values in metrics.items():
                rounds = {}
                for runtime, expected in values.items():
                    if runtime == "paired_ratios":
                        continue
                    selected = [row for row in measured
                                if row["workload"] == workload
                                and row["runtime"] == runtime
                                and row[metric] is not None]
                    rounds[runtime] = {row["round"]: row[metric] for row in selected}
                    require(len(rounds[runtime]) == len(selected),
                            f"duplicate round: {name}/{workload}/{runtime}")
                    actual = summary([row[metric] for row in selected])
                    require(all(same(actual[key], value)
                                for key, value in expected.items()),
                            f"summary mismatch: {name}/{workload}/{runtime}/{metric}")
                for label, expected in values["paired_ratios"].items():
                    if expected is None:
                        continue
                    left = expected["numerator_runtime"]
                    right = expected["denominator_runtime"]
                    shared = sorted(set(rounds[left]) & set(rounds[right]))
                    ratios = [rounds[left][index] / rounds[right][index]
                              for index in shared]
                    require(shared == expected["paired_rounds"]
                            and len(ratios) == expected["n"]
                            and same(statistics.median(ratios), expected["median_ratio"]),
                            f"paired median mismatch: {name}/{workload}/{label}/{metric}")
                    if bootstrap and label == "baseline_node_over_fork_node":
                        actual = paired_ratio(rounds[left], rounds[right], left,
                                              right, report["seed"])
                        require(all(same(actual[key], value)
                                    for key, value in expected.items()),
                                f"bootstrap mismatch: {name}/{workload}/{metric}")
                    comparisons += 1
        print(f"{name}: {len(records)} samples, {failures} failed samples verified",
              flush=True)
    print(f"Verified {len(manifest['files'])} hashes, {samples} samples, "
          f"{comparisons} paired summaries; bootstrap={bootstrap}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", action="store_true",
                        help="also recompute all control/candidate bootstrap intervals")
    verify(parser.parse_args().bootstrap)
