#!/usr/bin/env python3
"""Run reproducible, interleaved startup measurements for direct runtimes."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import os
import platform
import random
import re
import selectors
import signal
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
DEFAULT_WORKLOADS = ("eval-empty", "empty-cjs", "empty-esm", "hello", "builtins", "http-ready", "crypto-first-use", "worker")
UNSAFE_ENV = ("NODE_OPTIONS", "BUN_OPTIONS", "NODE_PATH", "NODE_V8_COVERAGE", "NODE_COMPILE_CACHE", "NODE_DISABLE_COMPILE_CACHE", "NODE_REPL_HISTORY")


@dataclass(frozen=True)
class Workload:
    name: str
    args: tuple[str, ...]
    marker: bool
    runtime_kinds: tuple[str, ...] = ("node", "bun")


WORKLOADS = {
    "eval-empty": Workload("eval-empty", ("-e", ""), False),
    "empty-cjs": Workload("empty-cjs", (str(FIXTURES / "empty.cjs"),), False),
    "empty-esm": Workload("empty-esm", (str(FIXTURES / "empty.mjs"),), False),
    "hello": Workload("hello", (str(FIXTURES / "hello.cjs"),), True),
    "builtins": Workload("builtins", (str(FIXTURES / "builtins.cjs"),), True),
    "http-ready": Workload("http-ready", (str(FIXTURES / "http-ready.cjs"),), True),
    "crypto-first-use": Workload("crypto-first-use", (str(FIXTURES / "crypto-first-use.cjs"),), True),
    # Bun's Worker URL and lifetime behavior differs across releases; record it separately.
    "worker": Workload("worker", (str(FIXTURES / "worker.cjs"),), True, ("node",)),
}


def direct_path(value: str) -> str:
    path = Path(value).expanduser().resolve()
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise argparse.ArgumentTypeError(f"runtime must be an executable absolute path: {value}")
    return str(path)


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_output(args: list[str]) -> str | None:
    try:
        return subprocess.run(args, stdin=subprocess.DEVNULL, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def machine_metadata() -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "platform": platform.platform(), "python": sys.version, "machine": platform.machine(),
        "processor": platform.processor(), "cpu_count": os.cpu_count(),
    }
    if sys.platform == "darwin":
        for key in ("machdep.cpu.brand_string", "hw.memsize", "kern.osproductversion"):
            value = command_output(["/usr/sbin/sysctl", "-n", key])
            if value:
                metadata[key] = value
    return metadata


def file_sha256(path: Path) -> str:
    return sha256(str(path))


IDENTITY_CONFIG_KEYS = frozenset({"prefix", "srcdir", "builddir", "source_dir", "build_dir", "abs_srcdir", "abs_builddir", "workdir", "work_dir"})
# configure.py derives this list solely from test/cctest; node.gyp consumes it only
# in the cctest executable target, not the Node runtime target.
NON_RUNTIME_CONFIG_KEYS = frozenset({"node_cctest_sources"})


def normalize_config(value: Any, key: str | None = None) -> Any:
    if key is not None:
        if key.lower() in IDENTITY_CONFIG_KEYS:
            return "<identity-path>"
        if key in NON_RUNTIME_CONFIG_KEYS:
            return "<non-runtime-cctest-sources>"
    if isinstance(value, dict):
        return {str(child_key): normalize_config(child_value, str(child_key)) for child_key, child_value in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return [normalize_config(child) for child in value]
    return value


def find_config_value(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in keys:
                return child
            found = find_config_value(child, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_config_value(child, keys)
            if found is not None:
                return found
    return None


def config_metadata(config: Path | None) -> dict[str, Any] | None:
    if config is None:
        return None
    path = config.expanduser().resolve()
    text = path.read_text()
    document = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    try:
        parsed = json.loads(document)
        parser = "json"
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(document)
            parser = "python-literal"
        except (SyntaxError, ValueError):
            parsed = {"__unparsed_file_sha256__": file_sha256(path)}
            parser = "unparsed-file-hash"
    return {"path": str(path), "sha256": file_sha256(path), "parser": parser, "normalizer": "recursive-v3; identity-path values plus node_cctest_sources (cctest-only) are ignored", "normalized_config": normalize_config(parsed)}


def build_characteristics(config: dict[str, Any] | None) -> dict[str, str | None]:
    document = None if config is None else config["normalized_config"]
    default_configuration = find_config_value(document, {"default_configuration"})
    debug = find_config_value(document, {"is_debug", "debug", "node_debug_lib"})
    snapshot = find_config_value(document, {"node_use_node_snapshot", "v8_use_snapshot", "use_snapshot"})
    if default_configuration is not None:
        release_mode = str(default_configuration).lower()
    elif debug is not None:
        release_mode = "debug" if str(debug).lower() in {"1", "true", "yes"} else "release"
    else:
        release_mode = None
    return {"release_mode": release_mode, "snapshot": None if snapshot is None else str(snapshot)}


def source_provenance(name: str, source: Path | None, output: Path) -> dict[str, str | bool | None]:
    if source is None:
        return {"source_path": None, "source_git_head": None, "source_dirty": None, "source_status": None, "source_diff_file": None}
    source = source.expanduser().resolve()
    status = command_output(["/usr/bin/git", "-C", str(source), "status", "--short"])
    head = command_output(["/usr/bin/git", "-C", str(source), "rev-parse", "HEAD"])
    try:
        diff = subprocess.run(["/usr/bin/git", "-C", str(source), "diff", "--binary", "HEAD"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        diff = b""
    provenance_dir = output / "provenance"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    diff_file = provenance_dir / f"{name}.source.diff"
    diff_file.write_bytes(diff)
    return {"source_path": str(source), "source_git_head": head, "source_dirty": bool(status), "source_status": status, "source_diff_file": str(diff_file)}


def build_manifest_metadata(manifest_path: Path | None, binary_hash: str, build_config: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest_path is None:
        return None
    path = manifest_path.expanduser().resolve()
    try:
        contents = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return {"path": str(path), "sha256": None, "contents": None, "validated": False, "error": str(error)}
    if not isinstance(contents, dict):
        return {"path": str(path), "sha256": file_sha256(path), "contents": contents, "validated": False, "error": "manifest must be a JSON object"}
    binary_matches = contents.get("binary_sha256") == binary_hash
    expected_config = contents.get("config_sha256")
    config_matches = None if build_config is None else expected_config == build_config["sha256"]
    return {"path": str(path), "sha256": file_sha256(path), "contents": contents, "binary_sha256_matches": binary_matches, "config_sha256_matches": config_matches, "validated": binary_matches and config_matches is not False, "error": None}


def runtime_metadata(name: str, path: str, source: dict[str, str | bool | None], config: Path | None, manifest: Path | None) -> dict[str, Any]:
    stat = Path(path).stat()
    build_config = config_metadata(config)
    binary_hash = sha256(path)
    return {
        "name": name,
        "path": path,
        "sha256": binary_hash,
        "version": command_output([path, "--version"]),
        "revision": command_output([path, "--revision"]),
        "binary_size_bytes": stat.st_size,
        "binary_mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
        "binary_architecture": command_output(["/usr/bin/file", "-b", path]),
        "binary_linkage": command_output(["/usr/bin/otool", "-L", path]) if sys.platform == "darwin" else None,
        "source": source,
        "build_config": build_config,
        "build_characteristics": build_characteristics(build_config),
        "build_manifest": build_manifest_metadata(manifest, binary_hash, build_config),
    }


def sanitized_environment(timezone: str = "utc") -> tuple[dict[str, str], dict[str, str | None]]:
    environment = os.environ.copy()
    removed = {key: environment.pop(key, None) for key in UNSAFE_ENV}
    for key in list(environment):
        if key.startswith(("NODE_", "__NUB_")):
            environment.pop(key)
            # Runtime and wrapper bookkeeping can contain credentials.
            removed[key] = "<redacted>"
    environment["NO_COLOR"] = "1"
    environment["FORCE_COLOR"] = "0"
    if timezone == "utc":
        environment["TZ"] = "UTC"
    elif timezone == "system":
        environment.pop("TZ", None)
    else:
        raise ValueError(f"unsupported timezone mode: {timezone}")
    return environment, removed


def environment_policy(timezone: str, removed: dict[str, str | None]) -> dict[str, Any]:
    return {
        "inherited": "all parent variables except NODE_*, __NUB_* and listed removals; additional removed values are redacted; runner adds NO_COLOR=1 and FORCE_COLOR=0",
        "removed_values": removed,
        "timezone_mode": timezone,
        "timezone_override": {"TZ": "UTC" if timezone == "utc" else None},
    }


def run_once(runtime: str, workload: Workload, environment: dict[str, str], timeout: float) -> dict[str, Any]:
    ready_read: int | None = None
    ready_write: int | None = None
    child_env = environment.copy()
    if workload.marker:
        ready_read, ready_write = os.pipe()
        os.set_inheritable(ready_write, True)
        child_env["STARTUP_LAB_READY_FD"] = str(ready_write)
    started = time.monotonic_ns()
    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    exit_read: int | None = None
    reaper: threading.Thread | None = None
    exit_timestamp: list[int] = []
    try:
        process = subprocess.Popen([runtime, *workload.args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env, pass_fds=() if ready_write is None else (ready_write,), start_new_session=True)
        if ready_write is not None:
            os.close(ready_write)
            ready_write = None
        selector = selectors.DefaultSelector()
        stdout, stderr, marker = bytearray(), bytearray(), bytearray()
        marker_timestamp: int | None = None
        streams: dict[int, tuple[str, bytearray]] = {process.stdout.fileno(): ("stdout", stdout), process.stderr.fileno(): ("stderr", stderr)}
        if ready_read is not None:
            streams[ready_read] = ("ready", marker)
        for fd, (name, _) in streams.items():
            os.set_blocking(fd, False)
            selector.register(fd, selectors.EVENT_READ, name)
        exit_read, exit_write = os.pipe()
        os.set_blocking(exit_read, False)
        selector.register(exit_read, selectors.EVENT_READ, "exit")
        def reap() -> None:
            try:
                process.wait()
                exit_timestamp.append(time.monotonic_ns())
                try:
                    os.write(exit_write, b"x")
                except OSError:
                    pass
            finally:
                try:
                    os.close(exit_write)
                except OSError:
                    pass

        reaper = threading.Thread(target=reap, daemon=True)
        reaper.start()
        deadline = started + int(timeout * 1_000_000_000)
        cleanup_deadline: int | None = None
        timed_out = False
        exited_before_timeout = False
        while True:
            now = time.monotonic_ns()
            active_deadline = cleanup_deadline if cleanup_deadline is not None else deadline
            if now >= active_deadline:
                if cleanup_deadline is None:
                    exited_before_timeout = bool(exit_timestamp)
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    timed_out = True
                    cleanup_deadline = now + 1_000_000_000
                    continue
                status = "cleanup-error"
                error = "process-group cleanup timed out"
                break
            events = selector.select((active_deadline - now) / 1_000_000_000)
            for key, _ in events:
                fd, name = key.fd, key.data
                if name == "exit":
                    os.read(fd, 4096)
                    continue
                while True:
                    try:
                        chunk = os.read(fd, 65536)
                    except BlockingIOError:
                        break
                    if not chunk:
                        selector.unregister(fd)
                        streams.pop(fd)
                        break
                    if name == "ready" and not marker:
                        marker_timestamp = time.monotonic_ns()
                    streams[fd][1].extend(chunk)
            if exit_timestamp and not streams:
                status = "timeout" if timed_out and not exited_before_timeout else "cleanup-timeout" if timed_out else "ok" if process.returncode == 0 else "error"
                error = "child descendants retained output or readiness pipes" if status == "cleanup-timeout" else None
                break
        ended = exit_timestamp[0] if exit_timestamp else time.monotonic_ns()
        if status == "ok" and workload.marker and marker != b"1":
            status = "marker-missing" if not marker else "marker-invalid"
            error = "workload exited without readiness marker" if not marker else f"invalid readiness marker: {bytes(marker)!r}"
        return {"status": status, "exit_code": process.returncode, "exec_to_exit_ms": (ended - started) / 1e6, "workload_ready_ms": None if marker_timestamp is None or marker != b"1" else (marker_timestamp - started) / 1e6, "stdout": stdout.decode(errors="replace"), "stderr": stderr.decode(errors="replace"), "error": error}
    except OSError as error:
        return {"status": "launch-error", "exit_code": None, "exec_to_exit_ms": None, "workload_ready_ms": None, "stdout": "", "stderr": str(error), "error": str(error)}
    finally:
        try:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        finally:
            try:
                if reaper is not None:
                    reaper.join() if exit_timestamp else reaper.join(timeout=1)
            finally:
                closers: list[object] = []
                if selector is not None:
                    closers.append(selector.close)
                if exit_read is not None:
                    closers.append(lambda: os.close(exit_read))
                if process is not None and process.stdout is not None:
                    closers.append(process.stdout.close)
                if process is not None and process.stderr is not None:
                    closers.append(process.stderr.close)
                if ready_write is not None:
                    closers.append(lambda: os.close(ready_write))
                if ready_read is not None:
                    closers.append(lambda: os.close(ready_read))
                for close in closers:
                    try:
                        close()
                    except (OSError, ValueError):
                        pass


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * fraction
    lower, upper = math.floor(index), math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def summary(values: list[float]) -> dict[str, float | int]:
    median = statistics.median(values)
    return {"n": len(values), "median_ms": median, "p90_ms": percentile(values, 0.9), "mad_ms": statistics.median([abs(value - median) for value in values])}


def paired_ratio(numerator: dict[int, float], denominator: dict[int, float], numerator_name: str, denominator_name: str, seed: int) -> dict[str, float | int | str] | None:
    rounds = sorted(set(numerator) & set(denominator))
    if not rounds:
        return None
    ratios = [numerator[round_number] / denominator[round_number] for round_number in rounds if denominator[round_number] > 0]
    if not ratios:
        return None
    randomizer = random.Random(seed)
    medians = [statistics.median([randomizer.choice(ratios) for _ in ratios]) for _ in range(2000)]
    return {"n": len(ratios), "paired_rounds": rounds, "numerator_runtime": numerator_name, "denominator_runtime": denominator_name, "median_ratio": statistics.median(ratios), "bootstrap_95_ci_low": percentile(medians, 0.025), "bootstrap_95_ci_high": percentile(medians, 0.975)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True, type=direct_path, help="absolute fork Node executable")
    parser.add_argument("--baseline-node", type=direct_path, help="optional pristine baseline Node executable")
    parser.add_argument("--release-node", type=direct_path, help="optional release Node executable")
    parser.add_argument("--bun", required=True, type=direct_path, help="absolute Bun executable")
    parser.add_argument("--runs", type=int, default=30, help="measured interleaved rounds per workload")
    parser.add_argument("--warmups", type=int, default=5, help="unrecorded interleaved rounds per workload")
    parser.add_argument("--seed", type=int, default=20260906)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--timezone", choices=("utc", "system"), default="utc", help="child timezone policy: UTC or no TZ override")
    parser.add_argument("--workloads", nargs="+", choices=sorted(WORKLOADS), default=list(DEFAULT_WORKLOADS))
    parser.add_argument("--output", type=Path, default=ROOT / "results")
    parser.add_argument("--node-source", type=Path, help="optional fork Node source checkout")
    parser.add_argument("--baseline-source", type=Path, help="optional pristine baseline source checkout")
    parser.add_argument("--release-source", type=Path, help="optional release Node source checkout")
    parser.add_argument("--bun-source", type=Path, help="optional Bun source checkout; records its Git HEAD")
    parser.add_argument("--node-config", type=Path, help="optional fork Node build config to hash")
    parser.add_argument("--baseline-config", type=Path, help="optional baseline Node build config to hash")
    parser.add_argument("--release-config", type=Path, help="optional release Node build config to hash")
    parser.add_argument("--bun-config", type=Path, help="optional Bun build config to hash")
    parser.add_argument("--node-build-manifest", type=Path, help="optional fork build manifest from record_build.py")
    parser.add_argument("--baseline-build-manifest", type=Path, help="optional baseline build manifest from record_build.py")
    arguments = parser.parse_args()
    if arguments.runs < 1 or arguments.warmups < 0 or arguments.timeout <= 0:
        parser.error("runs must be positive; warmups must be nonnegative; timeout must be positive")
    return arguments


def prepare_output(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise ValueError(f"output path must be a directory: {path}")
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"output directory must be empty: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def node_comparability(runtimes: dict[str, dict[str, str]], metadata: dict[str, Any]) -> dict[str, Any]:
    if "baseline-node" not in runtimes:
        return {"status": "not-applicable", "reason": "--baseline-node was not supplied"}
    baseline, fork = metadata["baseline-node"], metadata["fork-node"]
    baseline_config, fork_config = baseline["build_config"], fork["build_config"]
    config_matches = baseline_config is not None and fork_config is not None and baseline_config["normalized_config"] == fork_config["normalized_config"]
    known_architectures = re.compile(r"\b(arm64|aarch64|x86_64|amd64|i386)\b", re.IGNORECASE)
    architecture_matches = baseline["binary_architecture"] is not None and fork["binary_architecture"] is not None and known_architectures.search(baseline["binary_architecture"]) is not None and baseline["binary_architecture"] == fork["binary_architecture"]
    artifact_directory_matches = str(Path(baseline["path"]).parent) == str(Path(fork["path"]).parent)
    release_mode_matches = baseline["build_characteristics"]["release_mode"] is not None and baseline["build_characteristics"]["release_mode"] == fork["build_characteristics"]["release_mode"]
    snapshot_matches = baseline["build_characteristics"]["snapshot"] is not None and baseline["build_characteristics"]["snapshot"] == fork["build_characteristics"]["snapshot"]
    manifests = (baseline["build_manifest"], fork["build_manifest"])
    manifest_valid = all(manifest is None or manifest["validated"] for manifest in manifests)
    checks = {"normalized_config_matches": config_matches, "architecture_matches": architecture_matches, "same_artifact_directory": artifact_directory_matches, "release_mode_matches": release_mode_matches, "snapshot_matches": snapshot_matches, "build_manifests_validated": manifest_valid, "baseline_config_supplied": baseline_config is not None, "fork_config_supplied": fork_config is not None}
    if all((config_matches, architecture_matches, artifact_directory_matches, release_mode_matches, snapshot_matches, manifest_valid)):
        return {"status": "verified-comparable", "checks": checks}
    return {"status": "exploratory-not-verified-comparable", "checks": checks, "reason": "Configuration, architecture, or artifact-directory evidence is absent or differs. Do not attribute any ratio to a fork patch."}


def main() -> int:
    args = parse_args()
    selected = [WORKLOADS[name] for name in args.workloads]
    environment, removed = sanitized_environment(args.timezone)
    runtimes: dict[str, dict[str, str]] = {"fork-node": {"path": args.node, "kind": "node"}, "bun": {"path": args.bun, "kind": "bun"}}
    if args.baseline_node:
        runtimes["baseline-node"] = {"path": args.baseline_node, "kind": "node"}
    if args.release_node:
        runtimes["release-node"] = {"path": args.release_node, "kind": "node"}
    try:
        args.output = prepare_output(args.output)
    except ValueError as error:
        raise SystemExit(f"startup-lab: {error}")
    sources = {"fork-node": source_provenance("fork-node", args.node_source, args.output), "baseline-node": source_provenance("baseline-node", args.baseline_source, args.output), "release-node": source_provenance("release-node", args.release_source, args.output), "bun": source_provenance("bun", args.bun_source, args.output)}
    configs = {"fork-node": args.node_config, "baseline-node": args.baseline_config, "release-node": args.release_config, "bun": args.bun_config}
    manifests = {"fork-node": args.node_build_manifest, "baseline-node": args.baseline_build_manifest, "release-node": None, "bun": None}
    metadata = {name: runtime_metadata(name, runtime["path"], sources[name], configs[name], manifests[name]) for name, runtime in runtimes.items()}
    machine = machine_metadata()
    comparability = {"baseline_node_vs_fork_node": node_comparability(runtimes, metadata)}
    jobs = [(workload, runtime_name) for workload in selected for runtime_name, runtime in runtimes.items() if runtime["kind"] in workload.runtime_kinds]
    randomizer = random.Random(args.seed)
    raw_path = args.output / "raw.jsonl"
    records: list[dict[str, Any]] = []
    with raw_path.open("x") as raw_output:
        for phase, count in (("warmup", args.warmups), ("measured", args.runs)):
            for round_number in range(count):
                round_jobs = jobs[:]
                randomizer.shuffle(round_jobs)
                for workload, runtime_name in round_jobs:
                    result = run_once(runtimes[runtime_name]["path"], workload, environment, args.timeout)
                    result.update({"phase": phase, "round": round_number, "workload": workload.name, "runtime": runtime_name, "marker_expected": workload.marker})
                    records.append(result)
                    raw_output.write(json.dumps(result, sort_keys=True) + "\n")
                    raw_output.flush()
                    os.fsync(raw_output.fileno())
                    if result["status"] == "cleanup-error":
                        raise RuntimeError("aborting after process-group cleanup error; raw.jsonl contains the failed sample")
    with (args.output / "raw.csv").open("w", newline="") as output:
        fields = ["phase", "round", "workload", "runtime", "status", "exit_code", "exec_to_exit_ms", "workload_ready_ms", "marker_expected", "stdout", "stderr", "error"]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(records)
    report: dict[str, Any] = {"schema": 3, "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seed": args.seed, "runs": args.runs, "warmups": args.warmups, "timeout_seconds": args.timeout, "environment_policy": environment_policy(args.timezone, removed), "machine": machine, "runtimes": metadata, "comparability": comparability, "workloads": {item.name: asdict(item) for item in selected}, "raw_files": {"jsonl": str(raw_path), "csv": str(args.output / "raw.csv")}, "summaries": {}}
    measured = [record for record in records if record["phase"] == "measured" and record["status"] == "ok"]
    for workload in selected:
        workload_report: dict[str, Any] = {}
        for metric in ("exec_to_exit_ms", "workload_ready_ms"):
            compatible = [name for name, runtime in runtimes.items() if runtime["kind"] in workload.runtime_kinds]
            values = {runtime: [record[metric] for record in measured if record["workload"] == workload.name and record["runtime"] == runtime and record[metric] is not None] for runtime in compatible}
            workload_report[metric] = {runtime: summary(samples) for runtime, samples in values.items() if samples}
            round_values = {runtime: {record["round"]: record[metric] for record in measured if record["workload"] == workload.name and record["runtime"] == runtime and record[metric] is not None} for runtime in compatible}
            comparisons = (("baseline_node_over_fork_node", "baseline-node", "fork-node"), ("baseline_node_over_bun", "baseline-node", "bun"), ("fork_node_over_bun", "fork-node", "bun"), ("release_node_over_bun", "release-node", "bun"))
            workload_report[metric]["paired_ratios"] = {label: paired_ratio(round_values[left], round_values[right], left, right, args.seed) for label, left, right in comparisons if left in round_values and right in round_values}
        report["summaries"][workload.name] = workload_report
    report_path = args.output / "report.json"
    temporary_report = args.output / ".report.json.tmp"
    temporary_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    os.replace(temporary_report, report_path)
    failures = [record for record in records if record["phase"] == "measured" and record["status"] != "ok"]
    print(f"wrote {args.output / 'report.json'}; {len(measured)} successful measured samples; {len(failures)} measured failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
