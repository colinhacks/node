#!/usr/bin/env python3
"""Measure paired peak RSS for direct Node artifacts on native Linux.

The runner is intentionally a guest-side tool.  It accepts only absolute
artifact paths, invokes them without a shell, records every child result, and
does not interpret a timing difference as an attribution to a loader feature.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = 1
UNSAFE_PREFIXES = ("NODE_", "__NUB_", "LD_")
UNSAFE_EXACT = ("LLVM_PROFILE_FILE",)
RSS_LABEL = "Maximum resident set size (kbytes):"
WORKER_PROGRAM = "const{Worker}=require('node:worker_threads');const w=new Worker('',{eval:true});w.once('exit',c=>process.exitCode=c);"


@dataclass(frozen=True)
class Artifact:
    name: str
    path: Path
    sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_artifact(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name or not raw_path:
        raise ValueError("--artifact must be NAME=/absolute/path")
    if not name.replace("_", "").replace("-", "").isalnum():
        raise ValueError("artifact names may contain letters, digits, '_' and '-'")
    path = Path(raw_path)
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"artifact {name!r} must be an existing executable absolute file")
    return name, path.resolve()


def load_artifacts(values: list[str]) -> dict[str, Artifact]:
    artifacts: dict[str, Artifact] = {}
    for value in values:
        name, path = parse_artifact(value)
        if name in artifacts:
            raise ValueError(f"duplicate artifact name: {name}")
        artifacts[name] = Artifact(name, path, sha256_file(path))
    if len(artifacts) < 2:
        raise ValueError("supply at least two --artifact values")
    baseline = next(iter(artifacts.values()))
    identity_name = f"{baseline.name}__identity"
    if identity_name in artifacts:
        raise ValueError(f"reserved automatic identity artifact name: {identity_name}")
    artifacts[identity_name] = Artifact(identity_name, baseline.path, baseline.sha256)
    return artifacts


def sanitized_environment() -> tuple[dict[str, str], list[str]]:
    environment = os.environ.copy()
    removed = sorted(key for key in environment if key.upper().startswith(UNSAFE_PREFIXES) or key.upper() in UNSAFE_EXACT)
    for key in removed:
        environment.pop(key, None)
    environment.update({"LC_ALL": "C", "LANG": "C", "NO_COLOR": "1", "FORCE_COLOR": "0"})
    return environment, removed


def workloads(directory: Path) -> dict[str, tuple[str, ...]]:
    directory.mkdir(parents=True, exist_ok=True)
    cjs, esm = directory / "empty.cjs", directory / "empty.mjs"
    for path, contents in ((cjs, "\n"), (esm, "\n")):
        path.write_text(contents, encoding="utf-8", newline="\n")
    return {"emptyCJS": (str(cjs),), "emptyESM": (str(esm),), "eval": ("-e", ""), "worker": ("-e", WORKER_PROGRAM)}


def parse_peak_rss(time_output: str) -> int:
    values: list[int] = []
    for line in time_output.splitlines():
        normalized = line.strip()
        if normalized.startswith(RSS_LABEL):
            raw = normalized[len(RSS_LABEL):].strip()
            if not raw.isdecimal():
                raise ValueError("/usr/bin/time peak RSS is not an unsigned integer")
            values.append(int(raw))
    if len(values) != 1:
        raise ValueError(f"expected exactly one {RSS_LABEL!r} line, found {len(values)}")
    if values[0] <= 0:
        raise ValueError("/usr/bin/time peak RSS must be positive")
    return values[0]


def run_one(artifact: Artifact, workload: str, argv: tuple[str, ...], cwd: Path, environment: dict[str, str], timeout: float) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(prefix="node-rss-", delete=False) as stream:
        time_path = Path(stream.name)
    command = ["/usr/bin/time", "-v", "-o", str(time_path), str(artifact.path), *argv]
    started_ns = time.monotonic_ns()
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            status, error = ("ok", None) if process.returncode == 0 else ("exit-error", f"child exited {process.returncode}")
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
            status, error = "timeout", f"exceeded {timeout} seconds"
        elapsed_ms = (time.monotonic_ns() - started_ns) / 1_000_000
        time_output = time_path.read_text(encoding="utf-8", errors="replace")
        result: dict[str, Any] = {"artifact": artifact.name, "artifact_path": str(artifact.path), "artifact_sha256": artifact.sha256, "workload": workload, "command": command, "stdout": stdout, "stderr": stderr, "time_output": time_output, "exit_code": process.returncode, "status": status, "error": error, "elapsed_ms": elapsed_ms}
        if status == "ok":
            try:
                result["peak_rss_kib"] = parse_peak_rss(time_output)
            except ValueError as exc:
                result.update(status="parse-error", error=str(exc))
        return result
    except OSError as exc:
        return {"artifact": artifact.name, "artifact_path": str(artifact.path), "artifact_sha256": artifact.sha256, "workload": workload, "command": command, "stdout": "", "stderr": str(exc), "time_output": "", "exit_code": None, "status": "launch-error", "error": str(exc), "elapsed_ms": None}
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        time_path.unlink(missing_ok=True)


def bootstrap_ratio_ci(ratios: list[float], seed: int, resamples: int = 2000) -> list[float] | None:
    if not ratios:
        return None
    randomizer = random.Random(seed)
    estimates = sorted(statistics.median([randomizer.choice(ratios) for _ in ratios]) for _ in range(resamples))
    return [estimates[math.floor(0.025 * (resamples - 1))], estimates[math.ceil(0.975 * (resamples - 1))]]


def summarize(records: list[dict[str, Any]], baseline: str, artifacts: dict[str, Artifact], seed: int) -> dict[str, Any]:
    summary: dict[str, Any] = {"metric": {"name": "peak_rss", "unit": "KiB", "direction": "lower-is-better", "source": "/usr/bin/time -v Maximum resident set size (kbytes)"}, "failures": sum(record["status"] != "ok" for record in records), "workloads": {}}
    for workload in sorted({record["workload"] for record in records}):
        grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in artifacts}
        for record in records:
            if record["workload"] == workload and record["status"] == "ok":
                grouped[record["artifact"]].append(record)
        values: dict[str, Any] = {}
        baseline_by_round = {record["round"]: record["peak_rss_kib"] for record in grouped[baseline]}
        for name, samples in grouped.items():
            rss = [sample["peak_rss_kib"] for sample in samples]
            ratios = [sample["peak_rss_kib"] / baseline_by_round[sample["round"]] for sample in samples if sample["round"] in baseline_by_round]
            values[name] = {"samples": len(rss), "median_peak_rss_kib": statistics.median(rss) if rss else None, "paired_ratio_to_baseline": {"median": statistics.median(ratios) if ratios else None, "bootstrap_95_ci": bootstrap_ratio_ci(ratios, seed + sum(map(ord, workload + name)))}}
        summary["workloads"][workload] = values
    return summary


def measure(artifacts: dict[str, Artifact], output: Path, rounds: int, timeout: float, seed: int) -> dict[str, Any]:
    if output.exists():
        raise ValueError(f"output directory must not already exist: {output}")
    if sys.platform != "linux":
        raise ValueError("linux_memory requires a native Linux host")
    if not Path("/usr/bin/time").is_file():
        raise ValueError("linux_memory requires GNU /usr/bin/time")
    output.mkdir(parents=True)
    environment, removed = sanitized_environment()
    cases = workloads(output / "fixtures")
    baseline = next(iter(artifacts))
    records: list[dict[str, Any]] = []
    manifest = {"schema": SCHEMA, "source": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__).resolve())}, "tool": {"path": "/usr/bin/time", "arguments": ["-v", "-o", "<per-record-temporary-file>"]}, "host": {"platform": sys.platform, "kernel": os.uname().release, "machine": os.uname().machine, "python": sys.version}, "artifacts": {name: {"path": str(artifact.path), "sha256_before": artifact.sha256} for name, artifact in artifacts.items()}, "sanitized_environment_variables": removed, "child_environment_overrides": {"LC_ALL": "C", "LANG": "C", "NO_COLOR": "1", "FORCE_COLOR": "0"}, "rounds": rounds, "seed": seed, "timeout_seconds": timeout}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    order_rng = random.Random(seed)
    for workload, argv in cases.items():
        for round_number in range(rounds):
            order = list(artifacts)
            order_rng.shuffle(order)
            for name in order:
                record = run_one(artifacts[name], workload, argv, output, environment, timeout)
                record["round"] = round_number
                record["order"] = order
                records.append(record)
                with (output / "records.jsonl").open("a", encoding="utf-8") as record_stream:
                    record_stream.write(json.dumps(record, sort_keys=True) + "\n")
    after = {name: sha256_file(artifact.path) for name, artifact in artifacts.items()}
    changed = {name: {"before": artifact.sha256, "after": after[name]} for name, artifact in artifacts.items() if artifact.sha256 != after[name]}
    report = {"schema": SCHEMA, "manifest": manifest, "artifacts": {name: {"path": str(artifact.path), "sha256_before": artifact.sha256, "sha256_after": after[name]} for name, artifact in artifacts.items()}, "records": records, "summary": summarize(records, baseline, artifacts, seed), "artifact_mutations": changed}
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if changed:
        raise ValueError(f"artifact hash changed during measurement: {', '.join(changed)}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", action="append", required=True, help="NAME=/absolute/path; first is baseline")
    parser.add_argument("--output", required=True, help="absolute output directory")
    parser.add_argument("--rounds", type=int, default=25)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=20260909)
    args = parser.parse_args(argv)
    try:
        output = Path(args.output)
        if not output.is_absolute() or args.rounds < 1 or args.timeout_seconds <= 0:
            raise ValueError("--output must be absolute; --rounds and --timeout-seconds must be positive")
        report = measure(load_artifacts(args.artifact), output, args.rounds, args.timeout_seconds, args.seed)
    except ValueError as exc:
        parser.error(str(exc))
    return 1 if report["summary"]["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
