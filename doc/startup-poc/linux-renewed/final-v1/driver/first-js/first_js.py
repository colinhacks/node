#!/usr/bin/env python3
"""Measure first-JavaScript arrival on native Linux or Windows.

This is an instrumented diagnostic.  It separates the parent-clock-to-first-JS
interval from complete process lifetime; it does not attribute either interval
to operating-system loading or any particular runtime subsystem.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paired_bench  # noqa: E402 - shared native containment and bootstrap helpers.


SCHEMA = 1
BUSYWAIT_NS = 25_000_000
TIMEOUT_SECONDS = 15.0
CJS_PROGRAM = "const first=process.hrtime.bigint();require('node:fs').writeSync(1,String(first)+'\\n');"
ESM_PROGRAM = "const first=process.hrtime.bigint();const fs=await import('node:fs');fs.writeSync(1,String(first)+'\\n');"
DELAY_PROGRAM = "const before=process.hrtime.bigint();const until=before+25000000n;while(process.hrtime.bigint()<until){};const after=process.hrtime.bigint();require('node:fs').writeSync(1,JSON.stringify({before:String(before),after:String(after)})+'\\n');"


@dataclass(frozen=True)
class Artifact:
    name: str
    path: Path
    sha256: str


class Clock:
    """A parent clock expressed in the same epoch and units as ``hrtime``."""

    def __init__(self) -> None:
        if sys.platform == "linux":
            if time_clock_gettime_ns is None or time_CLOCK_MONOTONIC is None:
                raise OSError("Python does not expose CLOCK_MONOTONIC")
            self.kind = "CLOCK_MONOTONIC"
            self._now: Callable[[], int] = lambda: time_clock_gettime_ns(time_CLOCK_MONOTONIC)
        elif sys.platform == "win32":
            self.kind = "QueryPerformanceCounter/frequency"
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            frequency = ctypes.c_longlong()
            if not kernel32.QueryPerformanceFrequency(ctypes.byref(frequency)) or frequency.value <= 0:
                raise OSError(ctypes.get_last_error(), "QueryPerformanceFrequency failed")
            counter_type = ctypes.c_longlong

            def qpc_ns() -> int:
                counter = counter_type()
                if not kernel32.QueryPerformanceCounter(ctypes.byref(counter)):
                    raise OSError(ctypes.get_last_error(), "QueryPerformanceCounter failed")
                return counter.value * 1_000_000_000 // frequency.value

            self._now = qpc_ns
        else:
            raise ValueError("first_js supports native Windows or native Linux only")

    def now_ns(self) -> int:
        return self._now()


# Keeping these aliases at module scope lets tests substitute the Linux clock
# without depending on the host that imports this module.
import time as _time
time_clock_gettime_ns = getattr(_time, "clock_gettime_ns", None)
time_CLOCK_MONOTONIC = getattr(_time, "CLOCK_MONOTONIC", None)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_artifact(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name or not raw_path:
        raise ValueError("--artifact must be NAME=ABS_PATH")
    if not name.replace("_", "").replace("-", "").isalnum():
        raise ValueError("artifact names may contain letters, digits, '_' and '-'")
    path = Path(raw_path)
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"artifact {name!r} must name an existing absolute file")
    path = path.resolve()
    paired_bench.direct_executable(path, f"artifact {name!r}")
    return name, path


def load_artifacts(values: list[str]) -> dict[str, Artifact]:
    artifacts: dict[str, Artifact] = {}
    for value in values:
        name, path = parse_artifact(value)
        if name in artifacts:
            raise ValueError(f"duplicate artifact name: {name}")
        artifacts[name] = Artifact(name, path, sha256_file(path))
    if not artifacts:
        raise ValueError("at least one --artifact is required")
    # The same-path identity run is a final-baseline control.  It makes a
    # measured difference auditable without claiming the runner caused none.
    baseline = next(iter(artifacts.values()))
    identity_name = f"{baseline.name}__identity"
    if identity_name in artifacts:
        raise ValueError(f"reserved automatic identity artifact name: {identity_name}")
    artifacts[identity_name] = Artifact(identity_name, baseline.path, baseline.sha256)
    return artifacts


def child_cases(root: Path) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    fixtures = root / "fixtures"
    fixtures.mkdir(exist_ok=True)
    cjs = fixtures / "first.cjs"
    esm = fixtures / "first.mjs"
    for path, contents in ((cjs, CJS_PROGRAM + "\n"), (esm, ESM_PROGRAM + "\n")):
        if path.exists():
            raise ValueError(f"refusing to overwrite fixture: {path}")
        path.write_text(contents, encoding="utf-8", newline="\n")
    return {"cjs": (str(cjs),), "esm": (str(esm),), "eval": ("-e", CJS_PROGRAM), "positive_delay": ("-e", DELAY_PROGRAM)}, {"first.cjs": sha256_file(cjs), "first.mjs": sha256_file(esm)}


def timing_cases(cases: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    """Exclude the preflight-only positive control from collected samples."""
    return {name: command for name, command in cases.items() if name != "positive_delay"}


def parse_child_timestamp(stdout: str) -> int:
    lines = stdout.splitlines()
    if len(lines) != 1 or not lines[0] or not lines[0].isdigit():
        raise ValueError("child stdout must contain exactly one unsigned decimal timestamp")
    value = int(lines[0])
    if value <= 0:
        raise ValueError("child timestamp must be positive")
    return value


def parse_positive_timestamps(stdout: str, parent_start_ns: int, parent_end_ns: int) -> tuple[int, int]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"positive control stdout is not one JSON document: {error.msg}") from error
    if not isinstance(value, dict) or set(value) != {"before", "after"}:
        raise ValueError("positive control stdout must contain only before and after timestamps")
    before, after = value["before"], value["after"]
    if not isinstance(before, str) or not before.isdigit() or not isinstance(after, str) or not after.isdigit():
        raise ValueError("positive control timestamps must be unsigned decimal strings")
    before_ns, after_ns = int(before), int(after)
    if not parent_start_ns <= before_ns <= after_ns <= parent_end_ns:
        raise ValueError("positive control child timestamps are outside parent clock brackets")
    if after_ns - before_ns < BUSYWAIT_NS:
        raise ValueError(f"positive control busy wait was shorter than {BUSYWAIT_NS} ns")
    return before_ns, after_ns


def run_native(command: list[str], cwd: Path, environment: dict[str, str], timeout: float) -> tuple[str, int | None, str, str, float | None, str | None]:
    if sys.platform == "win32":
        return paired_bench.run_windows(command, cwd, environment, timeout)
    return paired_bench.run_posix(command, cwd, environment, timeout)


def run_one(artifact: Artifact, case: str, argv: tuple[str, ...], cwd: Path, clock: Clock, timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    environment, removed = paired_bench.sanitized_environment({})
    command = [str(artifact.path), *argv]
    parent_start_ns = clock.now_ns()
    status, exit_code, stdout, stderr, process_lifetime_ms, error = run_native(command, cwd, environment, timeout)
    parent_end_ns = clock.now_ns()
    record: dict[str, Any] = {
        "artifact": artifact.name, "artifact_path": str(artifact.path), "artifact_sha256": artifact.sha256,
        "case": case, "argv": command, "status": status, "exit_code": exit_code, "stdout": stdout,
        "stderr": stderr, "error": error, "parent_start_ns": parent_start_ns, "parent_end_ns": parent_end_ns,
        "process_lifetime_ms": process_lifetime_ms, "sanitized_environment_keys": removed,
    }
    if status != "ok":
        return record
    if stderr:
        record.update(status="stderr-mismatch", error="child stderr was not empty", total_ms=(parent_end_ns - parent_start_ns) / 1_000_000)
        return record
    first_js_ns: int | None = None
    try:
        if case == "positive_delay":
            first_js_ns, after_js_ns = parse_positive_timestamps(stdout, parent_start_ns, parent_end_ns)
        else:
            first_js_ns = parse_child_timestamp(stdout)
            if not parent_start_ns <= first_js_ns <= parent_end_ns:
                raise ValueError("child hrtime is outside parent clock brackets")
    except ValueError as parse_error:
        record.update(status="clock-mismatch", error=str(parse_error), first_js_ns=first_js_ns, first_js_ms=None, total_ms=(parent_end_ns - parent_start_ns) / 1_000_000)
        return record
    record.update(first_js_ns=first_js_ns, first_js_ms=(first_js_ns - parent_start_ns) / 1_000_000, total_ms=(parent_end_ns - parent_start_ns) / 1_000_000)
    if case == "positive_delay":
        record.update(positive_after_js_ns=after_js_ns, positive_busywait_ns=after_js_ns - first_js_ns)
    return record


def sample_coverage(records: list[dict[str, Any]], artifacts: dict[str, Artifact], rounds: int, warmups: int) -> tuple[dict[str, Any], bool]:
    expected = {"preflight": 1, "warmup": warmups, "measured": rounds}
    cases = {"preflight": ("positive_delay",), "warmup": ("cjs", "esm", "eval"), "measured": ("cjs", "esm", "eval")}
    coverage: dict[str, Any] = {}
    complete = True
    for phase, count in expected.items():
        phase_coverage: dict[str, Any] = {}
        for case in cases[phase]:
            artifact_coverage: dict[str, Any] = {}
            for name in artifacts:
                observed = len([item for item in records if item.get("phase") == phase and item.get("case") == case and item.get("artifact") == name and item.get("status") == "ok"])
                artifact_coverage[name] = {"expected": count, "observed_ok": observed, "complete": observed == count}
                complete &= observed == count
            phase_coverage[case] = artifact_coverage
        coverage[phase] = phase_coverage
    return coverage, complete


def summarize(records: list[dict[str, Any]], artifacts: dict[str, Artifact], seed: int, rounds: int, warmups: int, clock: Clock, post_hashes: dict[str, str | None], sources: dict[str, str], fixture_hashes: dict[str, str]) -> dict[str, Any]:
    failures = [item for item in records if item["status"] != "ok"]
    coverage, samples_complete = sample_coverage(records, artifacts, rounds, warmups)
    measured = [item for item in records if item["phase"] == "measured" and item["case"] != "positive_delay"]
    cases = ("cjs", "esm", "eval")
    metrics = ("first_js_ms", "total_ms", "process_lifetime_ms")
    comparisons: dict[str, Any] = {}
    names = list(artifacts)
    for case in cases:
        by_case = [item for item in measured if item["case"] == case]
        case_summary: dict[str, Any] = {}
        for metric in metrics:
            samples = {name: [item[metric] for item in by_case if item["artifact"] == name and item["status"] == "ok" and item[metric] is not None] for name in names}
            pairs: dict[str, Any] = {}
            for left_index, left in enumerate(names):
                for right in names[left_index + 1:]:
                    left_by_round = {item["round"]: item[metric] for item in by_case if item["artifact"] == left and item["status"] == "ok" and item[metric] is not None}
                    right_by_round = {item["round"]: item[metric] for item in by_case if item["artifact"] == right and item["status"] == "ok" and item[metric] is not None}
                    shared = sorted(set(left_by_round) & set(right_by_round))
                    ratios = [left_by_round[number] / right_by_round[number] for number in shared if right_by_round[number] > 0]
                    pairs[f"{left}_over_{right}"] = None if not ratios else {"paired_rounds": shared, "left_artifact": left, "right_artifact": right, "interpretation": "lower-than-one means the left artifact reaches this timestamp sooner", **paired_bench.paired_bootstrap(ratios, seed ^ int(hashlib.sha256(f"{case}:{metric}".encode()).hexdigest()[:8], 16))}
            case_summary[metric] = {"samples": {name: {"n": len(values), "median": paired_bench.statistics.median(values) if values else None, "p95": paired_bench.percentile(values, .95) if values else None} for name, values in samples.items()}, "paired_ratios": pairs}
        comparisons[case] = case_summary
    hashes = {name: {"path": str(item.path), "sha256_before": item.sha256, "sha256_after": post_hashes[name], "sha256_matches": item.sha256 == post_hashes[name]} for name, item in artifacts.items()}
    positive = [item for item in records if item["case"] == "positive_delay" and item["status"] == "ok"]
    positive_pass = len(positive) == len(artifacts) and all(item.get("positive_busywait_ns", 0) >= BUSYWAIT_NS for item in positive)
    return {"schema": SCHEMA, "verdict": "pass" if not failures and samples_complete and positive_pass and all(item["sha256_matches"] for item in hashes.values()) else "fail", "clock": {"parent": clock.kind, "child": "process.hrtime.bigint", "compatibility": "Linux uses CLOCK_MONOTONIC; Windows uses QueryPerformanceCounter/frequency."}, "host": paired_bench.host_metadata(), "sources": sources, "generated_fixture_sha256": fixture_hashes, "rounds": rounds, "warmups": warmups, "seed": seed, "busywait_ns": BUSYWAIT_NS, "positive_control_pass": positive_pass, "sample_coverage": coverage, "samples_complete": samples_complete, "failure_count": len(failures), "artifacts": hashes, "summaries": comparisons, "limitations": ["Instrumented parent-to-first-JavaScript and full-lifetime observations are separate diagnostics.", "Windows parent brackets include temporary Job and output-file setup in the shared runner before CreateProcess; they are not canonical CreateProcess-to-exit timing.", "No result attributes elapsed time to OS loader, V8, libuv, or another subsystem."]}


def prepare_output(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.exists() and any(path.iterdir()):
        raise ValueError("output directory must be empty; refusing to overwrite evidence")
    path.mkdir(parents=True, exist_ok=True)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", action="append", required=True, metavar="NAME=ABS_PATH")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=350)
    parser.add_argument("--warmups", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260908)
    args = parser.parse_args(argv)
    if args.rounds < 1 or args.warmups < 0:
        parser.error("--rounds must be positive and --warmups must be nonnegative")
    try:
        paired_bench.reject_non_native_host()
        artifacts, output, clock = load_artifacts(args.artifact), prepare_output(args.output), Clock()
        cases, fixture_hashes = child_cases(output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    records: list[dict[str, Any]] = []
    randomizer = random.Random(args.seed)
    raw_path = output / "raw.jsonl"
    with raw_path.open("x", encoding="utf-8", newline="\n") as stream:
        # A bounded preflight proves the child-side busy wait before the main
        # randomized timing collection.  It is not a sample in that collection.
        for artifact in artifacts.values():
            record = run_one(artifact, "positive_delay", cases["positive_delay"], output, clock)
            record.update(phase="preflight", round=0)
            records.append(record)
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
        os.fsync(stream.fileno())
        measurement_cases = timing_cases(cases)
        for phase, count in (("warmup", args.warmups), ("measured", args.rounds)):
            for round_number in range(count):
                jobs = [(case, artifact) for case in measurement_cases for artifact in artifacts.values()]
                randomizer.shuffle(jobs)
                for case, artifact in jobs:
                    record = run_one(artifact, case, measurement_cases[case], output, clock)
                    record.update(phase=phase, round=round_number)
                    records.append(record)
                    stream.write(json.dumps(record, sort_keys=True) + "\n")
                    stream.flush()
            os.fsync(stream.fileno())
    post_hashes: dict[str, str | None] = {}
    for name, artifact in artifacts.items():
        try:
            post_hashes[name] = sha256_file(artifact.path)
        except OSError:
            post_hashes[name] = None
    sources = {"probe": sha256_file(Path(__file__).resolve()), "shared_runner": sha256_file(Path(paired_bench.__file__).resolve())}
    report = summarize(records, artifacts, args.seed, args.rounds, args.warmups, clock, post_hashes, sources, fixture_hashes)
    (output / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "verdict": report["verdict"], "failure_count": report["failure_count"]}, sort_keys=True))
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
