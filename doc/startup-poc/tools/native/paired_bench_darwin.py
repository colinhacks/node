#!/usr/bin/env python3
"""Run direct, native Linux, macOS, and Windows paired measurements from JSON.

The runner deliberately has no SSH, shell, WSL, or package-manager mode.  Copy
the script, configuration, and already-built artifacts to the guest VM and run
it there.  Every invocation is a direct executable path and every child input
is recorded before results are summarized.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import io
import json
import math
import os
import platform
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


UNSAFE_PREFIXES = ("NODE_", "__NUB_")
BOOTSTRAP_RESAMPLES = 2_000


@dataclass(frozen=True)
class Artifact:
    name: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class Workload:
    name: str
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    metric_kind: str
    json_path: tuple[str, ...]
    expected_filename: str | None
    expected_stdout: str | None
    sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def reject_non_native_host() -> None:
    if sys.platform == "win32":
        return
    if sys.platform == "darwin":
        return
    if sys.platform != "linux":
        raise ValueError("paired_bench supports native Windows, Linux, or macOS only")
    release = ""
    for candidate in (Path("/proc/sys/kernel/osrelease"), Path("/proc/version")):
        try:
            release += candidate.read_text(errors="replace").lower()
        except OSError:
            pass
    if "microsoft" in release or "wsl" in release or os.environ.get("WSL_INTEROP"):
        raise ValueError("WSL is not a native Linux guest; run inside a Linux VM or physical host")


def absolute_existing_file(value: Any, label: str) -> Path:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string absolute path")
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"{label} must name an existing absolute file: {value!r}")
    return path.resolve()


def absolute_existing_dir(value: Any, label: str) -> Path:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string absolute path")
    path = Path(value)
    if not path.is_absolute() or not path.is_dir():
        raise ValueError(f"{label} must name an existing absolute directory: {value!r}")
    return path.resolve()


def direct_executable(path: Path, label: str) -> Path:
    """Validate an artifact that can be passed directly to the native launcher."""
    if sys.platform == "win32":
        # CreateProcessW receives the executable itself; accepting a .py, .cmd,
        # or association-dependent document would silently introduce a shell or
        # file-association layer into the measured invocation.
        if path.suffix.lower() not in (".exe", ".com"):
            raise ValueError(f"{label} is not executable as a direct Windows artifact (.exe or .com): {path}")
    elif not os.access(path, os.X_OK):
        raise ValueError(f"{label} is not executable: {path}")
    return path


def load_config(path: Path) -> tuple[dict[str, Any], dict[str, Artifact], list[Workload], int, int, float, int]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema") != 1:
        raise ValueError("config schema must be the integer 1")
    artifacts_raw = config.get("artifacts")
    if not isinstance(artifacts_raw, dict) or len(artifacts_raw) < 2:
        raise ValueError("config.artifacts must contain at least two named artifacts")
    artifacts: dict[str, Artifact] = {}
    for name, raw_path in artifacts_raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError("artifact names must be nonempty strings")
        executable = absolute_existing_file(raw_path, f"artifacts.{name}")
        executable = direct_executable(executable, f"artifacts.{name}")
        artifacts[name] = Artifact(name, executable, sha256_file(executable))
    workloads_raw = config.get("workloads")
    if not isinstance(workloads_raw, list) or not workloads_raw:
        raise ValueError("config.workloads must be a nonempty list")
    workloads: list[Workload] = []
    names: set[str] = set()
    for index, raw in enumerate(workloads_raw):
        if not isinstance(raw, dict):
            raise ValueError(f"workloads[{index}] must be an object")
        name, argv = raw.get("name"), raw.get("argv")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("workload names must be unique nonempty strings")
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            raise ValueError(f"workloads[{index}].argv must be a list of strings")
        cwd = absolute_existing_dir(raw.get("cwd"), f"workloads[{index}].cwd")
        additions = raw.get("env", {})
        if not isinstance(additions, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in additions.items()):
            raise ValueError(f"workloads[{index}].env must be a string map")
        forbidden = sorted(key for key in additions if key.upper().startswith(UNSAFE_PREFIXES))
        if forbidden:
            raise ValueError(f"workloads[{index}].env cannot restore sanitized variables: {', '.join(forbidden)}")
        metric = raw.get("metric", {"kind": "process-lifetime"})
        if not isinstance(metric, dict):
            raise ValueError(f"workloads[{index}].metric must be an object")
        kind = metric.get("kind")
        if kind not in ("process-lifetime", "json-throughput", "node-csv-throughput"):
            raise ValueError(f"workloads[{index}].metric.kind must be process-lifetime, json-throughput, or node-csv-throughput")
        selector = metric.get("json_path", "")
        expected_filename = metric.get("expected_filename")
        expected_stdout = raw.get("expected_stdout")
        if expected_stdout is not None and not isinstance(expected_stdout, str):
            raise ValueError(f"workloads[{index}].expected_stdout must be a string when supplied")
        if kind == "json-throughput" and (not isinstance(selector, str) or not selector):
            raise ValueError(f"workloads[{index}].metric.json_path is required for json-throughput")
        if kind != "json-throughput" and selector not in ("", None):
            raise ValueError(f"workloads[{index}].metric.json_path applies only to json-throughput")
        if kind == "node-csv-throughput" and (not isinstance(expected_filename, str) or not expected_filename):
            raise ValueError(f"workloads[{index}].metric.expected_filename is required for node-csv-throughput")
        if kind != "node-csv-throughput" and expected_filename is not None:
            raise ValueError(f"workloads[{index}].metric.expected_filename applies only to node-csv-throughput")
        names.add(name)
        normalized = {"name": name, "argv": argv, "cwd": str(cwd), "env": additions, "expected_stdout": expected_stdout, "metric": {"kind": kind, "json_path": selector or "", "expected_filename": expected_filename}}
        workloads.append(Workload(name, tuple(argv), cwd, dict(additions), kind, tuple(selector.split(".")) if selector else (), expected_filename, expected_stdout, canonical_hash(normalized)))
    rounds, warmups, timeout, seed = config.get("rounds", 15), config.get("warmups", 3), config.get("timeout_seconds", 60), config.get("seed", 20260908)
    if not isinstance(rounds, int) or rounds < 1 or not isinstance(warmups, int) or warmups < 0:
        raise ValueError("rounds must be positive and warmups must be nonnegative integers")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout_seconds must be positive")
    if not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    return config, artifacts, workloads, rounds, warmups, float(timeout), seed


def sanitized_environment(additions: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    environment = os.environ.copy()
    removed = sorted(key for key in environment if key.upper().startswith(UNSAFE_PREFIXES))
    for key in removed:
        environment.pop(key, None)
    environment.update(additions)
    environment["NO_COLOR"] = "1"
    environment["FORCE_COLOR"] = "0"
    return environment, removed


def extract_number(stdout: str, path: tuple[str, ...]) -> float:
    try:
        value: Any = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"stdout is not one JSON document: {error.msg}") from error
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"JSON path {'.'.join(path)!r} is absent")
        value = value[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f"JSON path {'.'.join(path)!r} must be a positive finite number")
    return float(value)


def extract_node_csv_throughput(stdout: str, expected_filename: str) -> float:
    """Parse exactly one row emitted by benchmark/run.js --format csv.

    Node's reporter deliberately prints a human-readable CSV header with spaces
    after its delimiters.  ``skipinitialspace`` recognizes that official form,
    while the parsed field names and row count remain exact.
    """
    try:
        rows = list(csv.reader(io.StringIO(stdout, newline=""), skipinitialspace=True))
    except csv.Error as error:
        raise ValueError(f"invalid Node benchmark CSV: {error}") from error
    if len(rows) != 2 or rows[0] != ["filename", "configuration", "rate", "time"]:
        raise ValueError("Node benchmark CSV must contain exactly the header filename,configuration,rate,time and one result row")
    row = rows[1]
    if len(row) != 4:
        raise ValueError("Node benchmark CSV result must contain exactly four fields")
    if row[0] != expected_filename:
        raise ValueError(f"Node benchmark filename mismatch: expected {expected_filename!r}, got {row[0]!r}")
    try:
        rate, elapsed = float(row[2]), float(row[3])
    except ValueError as error:
        raise ValueError("Node benchmark CSV rate and time must be numbers") from error
    if not math.isfinite(rate) or rate <= 0 or not math.isfinite(elapsed) or elapsed <= 0:
        raise ValueError("Node benchmark CSV rate and time must be positive finite numbers")
    return rate


def run_posix(command: list[str], cwd: Path, environment: dict[str, str], timeout: float) -> tuple[str, int | None, str, str, float | None, str | None]:
    started = time.monotonic_ns()
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd, env=environment, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            return "timeout", process.returncode, stdout, stderr, None, f"exceeded {timeout} seconds"
        elapsed = (time.monotonic_ns() - started) / 1_000_000
        return ("ok" if process.returncode == 0 else "exit-error"), process.returncode, stdout, stderr, elapsed, None
    except OSError as error:
        return "launch-error", None, "", str(error), None, str(error)
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


if sys.platform == "win32":
    import msvcrt

    from ctypes import wintypes

    class _STARTUPINFO(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD), ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE), ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("per_process", ctypes.c_longlong), ("per_job", ctypes.c_longlong), ("flags", wintypes.DWORD), ("minimum", ctypes.c_size_t), ("maximum", ctypes.c_size_t), ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("read_operation", "write_operation", "other_operation", "read_transfer", "write_transfer", "other_transfer")]

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("basic", _BASIC_LIMIT), ("io", _IO_COUNTERS), ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(_STARTUPINFO), ctypes.POINTER(_PROCESS_INFORMATION)]
    _kernel32.CreateProcessW.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    def _win_error(action: str) -> OSError:
        return OSError(ctypes.get_last_error(), f"{action}: {ctypes.FormatError(ctypes.get_last_error())}")

    def run_windows(command: list[str], cwd: Path, environment: dict[str, str], timeout: float) -> tuple[str, int | None, str, str, float | None, str | None]:
        # CreateProcess starts suspended so every child is assigned to the kill-on-close
        # Job before application code can create an uncontained descendant.
        process_info = _PROCESS_INFORMATION()
        job = None
        with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file, open("NUL", "rb") as stdin_file:
            for item in (stdout_file, stderr_file, stdin_file):
                os.set_inheritable(item.fileno(), True)
            startup = _STARTUPINFO()
            startup.cb = ctypes.sizeof(startup)
            startup.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
            startup.hStdInput = msvcrt.get_osfhandle(stdin_file.fileno())
            startup.hStdOutput = msvcrt.get_osfhandle(stdout_file.fileno())
            startup.hStdError = msvcrt.get_osfhandle(stderr_file.fileno())
            environment_block = ctypes.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in sorted(environment.items())) + "\0\0")
            command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
            try:
                job = _kernel32.CreateJobObjectW(None, None)
                if not job:
                    raise _win_error("CreateJobObjectW")
                limits = _EXTENDED_LIMIT()
                limits.basic.flags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                if not _kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                    raise _win_error("SetInformationJobObject")
                flags = 0x00000004 | 0x00000400 | 0x08000000  # suspended, Unicode env, no window
                # Start only at the CreateProcess call: temporary output-file and Job
                # construction are runner setup, not artifact execution time.
                started = time.monotonic_ns()
                if not _kernel32.CreateProcessW(None, command_line, None, None, True, flags, environment_block, str(cwd), ctypes.byref(startup), ctypes.byref(process_info)):
                    raise _win_error("CreateProcessW")
                if not _kernel32.AssignProcessToJobObject(job, process_info.hProcess):
                    raise _win_error("AssignProcessToJobObject")
                if _kernel32.ResumeThread(process_info.hThread) == 0xFFFFFFFF:
                    raise _win_error("ResumeThread")
                wait = _kernel32.WaitForSingleObject(process_info.hProcess, max(1, math.ceil(timeout * 1000)))
                if wait == 0x00000102:  # WAIT_TIMEOUT; close job below kills the whole tree.
                    _kernel32.CloseHandle(job); job = None
                    _kernel32.WaitForSingleObject(process_info.hProcess, 5_000)
                    stdout_file.seek(0); stderr_file.seek(0)
                    return "timeout", None, stdout_file.read().decode(errors="replace"), stderr_file.read().decode(errors="replace"), None, f"exceeded {timeout} seconds"
                if wait != 0:
                    raise _win_error("WaitForSingleObject")
                code = wintypes.DWORD()
                if not _kernel32.GetExitCodeProcess(process_info.hProcess, ctypes.byref(code)):
                    raise _win_error("GetExitCodeProcess")
                elapsed = (time.monotonic_ns() - started) / 1_000_000
                stdout_file.seek(0); stderr_file.seek(0)
                return ("ok" if code.value == 0 else "exit-error"), int(code.value), stdout_file.read().decode(errors="replace"), stderr_file.read().decode(errors="replace"), elapsed, None
            except OSError as error:
                # Assignment may fail after CreateProcess but before ResumeThread.  The
                # process is then suspended and outside the Job; terminate and reap it
                # explicitly instead of relying on close-job containment it never got.
                if process_info.hProcess:
                    _kernel32.TerminateProcess(process_info.hProcess, 1)
                    _kernel32.WaitForSingleObject(process_info.hProcess, 5_000)
                return "launch-error", None, "", str(error), None, str(error)
            finally:
                if process_info.hThread:
                    _kernel32.CloseHandle(process_info.hThread)
                if process_info.hProcess:
                    _kernel32.CloseHandle(process_info.hProcess)
                if job:
                    _kernel32.CloseHandle(job)


def run_once(artifact: Artifact, workload: Workload, timeout: float) -> dict[str, Any]:
    environment, removed = sanitized_environment(workload.env)
    command = [str(artifact.path), *workload.argv]
    if sys.platform == "win32":
        status, exit_code, stdout, stderr, elapsed, error = run_windows(command, workload.cwd, environment, timeout)
    else:
        status, exit_code, stdout, stderr, elapsed, error = run_posix(command, workload.cwd, environment, timeout)
    value = elapsed
    if status == "ok" and workload.metric_kind == "json-throughput":
        try:
            value = extract_number(stdout, workload.json_path)
        except ValueError as parse_error:
            status, error, value = "metric-error", str(parse_error), None
    if status == "ok" and workload.metric_kind == "node-csv-throughput":
        try:
            assert workload.expected_filename is not None
            value = extract_node_csv_throughput(stdout, workload.expected_filename)
        except ValueError as parse_error:
            status, error, value = "metric-error", str(parse_error), None
    if status == "ok" and workload.expected_stdout is not None and stdout != workload.expected_stdout:
        status, error = "stdout-mismatch", "stdout did not match workload.expected_stdout exactly"
    return {"status": status, "error": error, "exit_code": exit_code, "stdout": stdout, "stderr": stderr, "metric_kind": workload.metric_kind, "metric_value": value, "argv": command, "cwd": str(workload.cwd), "sanitized_environment_keys": removed}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def paired_bootstrap(values: list[float], seed: int) -> dict[str, float | int]:
    randomizer = random.Random(seed)
    resampled = [statistics.median([randomizer.choice(values) for _ in values]) for _ in range(BOOTSTRAP_RESAMPLES)]
    return {"n": len(values), "median_ratio": statistics.median(values), "bootstrap_resamples": BOOTSTRAP_RESAMPLES, "bootstrap_95_ci_low": percentile(resampled, .025), "bootstrap_95_ci_high": percentile(resampled, .975)}


def host_metadata() -> dict[str, Any]:
    return {"platform": platform.platform(), "system": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": sys.version, "python_executable": sys.executable, "cpu_count": os.cpu_count(), "runner_sha256": sha256_file(Path(__file__).resolve())}


def prepare_output(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.exists() and any(path.iterdir()):
        raise ValueError("output directory must be empty")
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_report(records: list[dict[str, Any]], artifacts: dict[str, Artifact], workloads: list[Workload], config_hash: str, seed: int, rounds: int, warmups: int, timeout: float, post_run_hashes: dict[str, str | None], post_run_hash_errors: dict[str, str]) -> dict[str, Any]:
    failures = [record for record in records if record["status"] != "ok"]
    comparisons: dict[str, Any] = {}
    for workload in workloads:
        workload_records = [record for record in records if record["phase"] == "measured" and record["workload"] == workload.name]
        per_artifact: dict[str, list[float]] = {name: [record["metric_value"] for record in workload_records if record["artifact"] == name and record["status"] == "ok" and record["metric_value"] is not None] for name in artifacts}
        pairs: dict[str, Any] = {}
        names = sorted(artifacts)
        for left_index, left in enumerate(names):
            for right in names[left_index + 1:]:
                left_values = {record["round"]: record["metric_value"] for record in workload_records if record["artifact"] == left and record["status"] == "ok"}
                right_values = {record["round"]: record["metric_value"] for record in workload_records if record["artifact"] == right and record["status"] == "ok"}
                shared = sorted(set(left_values) & set(right_values))
                ratios = [left_values[round_id] / right_values[round_id] for round_id in shared if right_values[round_id] > 0]
                label = f"{left}_over_{right}"
                pairs[label] = None if not ratios else {"left_artifact": left, "right_artifact": right, "paired_rounds": shared, **paired_bootstrap(ratios, seed ^ int(workload.sha256[:8], 16))}
        sample_summaries = {name: {"n": len(values), "median": statistics.median(values) if values else None, "p50": statistics.median(values) if values else None, "p95": percentile(values, .95) if values else None, "min": min(values) if values else None, "max": max(values) if values else None} for name, values in per_artifact.items()}
        ratio_interpretation = "lower-than-one means the left artifact has lower latency" if workload.metric_kind == "process-lifetime" else "greater-than-one means the left artifact has higher throughput"
        for value in pairs.values():
            if value is not None:
                value["interpretation"] = ratio_interpretation
        comparisons[workload.name] = {"metric_kind": workload.metric_kind, "ratio_interpretation": ratio_interpretation, "samples": sample_summaries, "paired_ratios": pairs}
    artifact_report: dict[str, dict[str, Any]] = {}
    for name, item in artifacts.items():
        try:
            size_bytes = item.path.stat().st_size
        except OSError:
            size_bytes = None
        artifact_report[name] = {"path": str(item.path), "sha256_before": item.sha256, "sha256_after": post_run_hashes[name], "sha256_matches": item.sha256 == post_run_hashes[name], "post_run_hash_error": post_run_hash_errors.get(name), "size_bytes": size_bytes}
    hash_failures = [name for name, item in artifact_report.items() if not item["sha256_matches"]]
    return {"schema": 1, "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "verdict": "fail" if failures or hash_failures else "pass", "failure_count": len(failures), "artifact_hash_failures": hash_failures, "seed": seed, "rounds": rounds, "warmups": warmups, "timeout_seconds": timeout, "config_sha256": config_hash, "host": host_metadata(), "artifacts": artifact_report, "workloads": {item.name: {"argv": list(item.argv), "cwd": str(item.cwd), "env": item.env, "expected_stdout": item.expected_stdout, "metric_kind": item.metric_kind, "json_path": ".".join(item.json_path), "expected_filename": item.expected_filename, "sha256": item.sha256} for item in workloads}, "summaries": comparisons}


def windows_selftest() -> int:
    """Exercise Job containment, large redirected output, and timeout locally.

    This mode uses only the running Python interpreter and temporary scripts, so
    it is suitable for a freshly provisioned Windows VM before any Node artifact
    is copied there.  A child escaping the Job would write ``escaped.txt`` after
    its parent exits; a timed-out process verifies the close-job path as well.
    """
    if sys.platform != "win32":
        print("windows selftest requires native Windows", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="paired-bench-selftest-") as directory:
        root = Path(directory)
        escaped = root / "escaped.txt"
        descendant = f"import time; time.sleep(.5); open({str(escaped)!r}, 'w').write('escaped')"
        flood = root / "flood.py"
        flood.write_text(f"import subprocess, sys\nsys.stdout.write('x' * (2 * 1024 * 1024))\nsys.stderr.write('e' * (2 * 1024 * 1024))\nsubprocess.Popen([sys.executable, '-c', {descendant!r}])\n", encoding="utf-8")
        sleeper = root / "sleeper.py"
        sleeper.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
        nonzero = root / "nonzero.py"
        nonzero.write_text("raise SystemExit(7)\n", encoding="utf-8")
        unicode_args = root / "unicode args.py"
        unicode_args.write_text("import os, sys\nassert sys.argv[1:] == ['space argument', '雪']\nassert os.environ['PAIRED_BENCH_SELFTEST'] == '✓ value'\nsys.stdout.write('unicode-ok')\n", encoding="utf-8")
        artifact = Artifact("python", Path(sys.executable).resolve(), sha256_file(Path(sys.executable).resolve()))
        base = {"name": "selftest", "argv": [], "cwd": str(root), "env": {}, "metric": {"kind": "process-lifetime", "json_path": "", "expected_filename": None}}
        flood_workload = Workload("flood", (str(flood),), root, {}, "process-lifetime", (), None, None, canonical_hash(base))
        timeout_workload = Workload("timeout", (str(sleeper),), root, {}, "process-lifetime", (), None, None, canonical_hash({**base, "name": "timeout"}))
        nonzero_workload = Workload("nonzero", (str(nonzero),), root, {}, "process-lifetime", (), None, None, canonical_hash({**base, "name": "nonzero"}))
        unicode_workload = Workload("unicode", (str(unicode_args), "space argument", "雪"), root, {"PAIRED_BENCH_SELFTEST": "✓ value"}, "process-lifetime", (), None, "unicode-ok", canonical_hash({**base, "name": "unicode"}))
        missing_artifact = Artifact("missing", root / "missing executable.exe", "missing")
        flood_result = run_once(artifact, flood_workload, 5)
        time.sleep(.8)
        timeout_result = run_once(artifact, timeout_workload, .1)
        nonzero_result = run_once(artifact, nonzero_workload, 5)
        unicode_result = run_once(artifact, unicode_workload, 5)
        missing_result = run_once(missing_artifact, flood_workload, 5)
        passed = flood_result["status"] == "ok" and len(flood_result["stdout"]) >= 2 * 1024 * 1024 and len(flood_result["stderr"]) >= 2 * 1024 * 1024 and not escaped.exists() and timeout_result["status"] == "timeout" and nonzero_result["status"] == "exit-error" and nonzero_result["exit_code"] == 7 and unicode_result["status"] == "ok" and missing_result["status"] == "launch-error"
        print(json.dumps({"selftest": "pass" if passed else "fail", "flood_status": flood_result["status"], "flood_stdout_bytes": len(flood_result["stdout"]), "flood_stderr_bytes": len(flood_result["stderr"]), "descendant_escaped": escaped.exists(), "timeout_status": timeout_result["status"], "nonzero_status": nonzero_result["status"], "unicode_status": unicode_result["status"], "missing_status": missing_result["status"]}, sort_keys=True))
        return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="absolute schema-1 JSON configuration")
    parser.add_argument("--output", type=Path, help="empty output directory")
    parser.add_argument("--windows-selftest", action="store_true", help="run native Windows Job Object self-test without Node fixtures")
    args = parser.parse_args(argv)
    if args.windows_selftest:
        if args.config or args.output:
            parser.error("--windows-selftest cannot be combined with --config or --output")
        return windows_selftest()
    if args.config is None or args.output is None:
        parser.error("--config and --output are required unless --windows-selftest is used")
    try:
        reject_non_native_host()
        config_path = absolute_existing_file(str(args.config.expanduser()), "--config")
        config, artifacts, workloads, rounds, warmups, timeout, seed = load_config(config_path)
        output = prepare_output(args.output)
    except (ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    config_hash = sha256_file(config_path)
    records: list[dict[str, Any]] = []
    raw_path = output / "raw.jsonl"
    randomizer = random.Random(seed)
    with raw_path.open("x", encoding="utf-8") as raw:
        for phase, count in (("warmup", warmups), ("measured", rounds)):
            for round_number in range(count):
                jobs = [(workload, artifact) for workload in workloads for artifact in artifacts.values()]
                randomizer.shuffle(jobs)
                for workload, artifact in jobs:
                    record = run_once(artifact, workload, timeout)
                    record.update({"phase": phase, "round": round_number, "artifact": artifact.name, "artifact_sha256": artifact.sha256, "workload": workload.name, "workload_sha256": workload.sha256, "config_sha256": config_hash})
                    records.append(record)
                    raw.write(json.dumps(record, sort_keys=True) + "\n")
                    raw.flush(); os.fsync(raw.fileno())
    post_run_hashes: dict[str, str | None] = {}
    post_run_hash_errors: dict[str, str] = {}
    for name, item in artifacts.items():
        try:
            post_run_hashes[name] = sha256_file(item.path)
        except OSError as error:
            post_run_hashes[name] = None
            post_run_hash_errors[name] = str(error)
    report = make_report(records, artifacts, workloads, config_hash, seed, rounds, warmups, timeout, post_run_hashes, post_run_hash_errors)
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output / 'report.json'}; verdict={report['verdict']}; failures={report['failure_count']}")
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
