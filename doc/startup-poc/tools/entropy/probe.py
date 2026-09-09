#!/usr/bin/env python3
"""Run bounded OpenSSL/V8 entropy differential probes against native Node binaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parent
WORKLOAD = ROOT / "entropy-workload.cjs"
BASE_ONLY = ROOT / "configs" / "base-only.cnf"
RANDOM_UNAVAILABLE = ROOT / "configs" / "random-unavailable.cnf"


def clean_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith("NODE_") or key.startswith("__NUB_"):
            environment.pop(key)
    for key in ("OPENSSL_CONF", "LLVM_PROFILE_FILE"):
        environment.pop(key, None)
    environment["LC_ALL"] = "C"
    if extra:
        environment.update(extra)
    return environment


def native_binary(binary: Path) -> dict[str, str]:
    with binary.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    return {
        "path": str(binary.resolve()),
        "sha256": digest,
    }


def parse_json_line(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def run_case(
    binary: Path,
    name: str,
    mode: str,
    node_args: list[str],
    env: dict[str, str],
    timeout: float,
    iterations: int,
) -> dict[str, Any]:
    command = [str(binary), *node_args, str(WORKLOAD)]
    child_env = clean_environment({"ENTROPY_MODE": mode, "ENTROPY_ITERATIONS": str(iterations), **env})
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        env=child_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
    elapsed_ms = (time.monotonic() - started) * 1000
    return {
        "name": name,
        "command": command,
        "mode": mode,
        "returncode": process.returncode,
        "timed_out": timed_out,
        "elapsed_ms": elapsed_ms,
        "payload": parse_json_line(stdout),
        "stdout": stdout,
        "stderr": stderr,
    }


def started(case: dict[str, Any]) -> bool:
    return not case["timed_out"] and case["returncode"] == 0 and bool(case["payload"] and case["payload"].get("ok"))


def aborted(case: dict[str, Any]) -> bool:
    return not case["timed_out"] and case["returncode"] == -signal.SIGABRT


def failed_without_abort(case: dict[str, Any]) -> bool:
    return not case["timed_out"] and case["returncode"] is not None and case["returncode"] > 0


def candidate_invariant(name: str, case: dict[str, Any]) -> tuple[bool, str]:
    payload = case["payload"] or {}
    if name == "default":
        return started(case) and payload.get("sha256Available") is True, "default startup and SHA-256 must work"
    elif name == "legacy":
        return started(case) and payload.get("sha256Available") is True and (payload.get("fips") or payload.get("md4Available") is True), "legacy mode must retain default crypto; MD4 is skipped by FIPS"
    elif name == "fips-request":
        return failed_without_abort(case) or (started(case) and payload.get("fips") == 1), "a FIPS request must start with FIPS enabled or report a normal startup error"
    elif name == "fips-configured-startup":
        return started(case) and payload.get("fips") == 1, "a supplied configured FIPS startup must enable FIPS"
    elif name.startswith("base-"):
        return aborted(case), "base-only configuration must terminate with SIGABRT before first crypto use"
    elif name.startswith("missing-") and name.endswith("-crypto"):
        return failed_without_abort(case) and "fetch drbg" in json.dumps(payload.get("error", {})).lower(), "unavailable DRBG must fail on first crypto use without a hang"
    elif name.startswith("missing-") and name.endswith("-startup"):
        return started(case), "unavailable DRBG startup deferral is a disclosed PR behavior"
    elif name == "secure-heap-workers":
        return started(case), "secure-heap worker failures must not abort the candidate process"
    elif name in ("first-crypto", "throughput"):
        return started(case), "measurement workload must complete"
    raise ValueError(f"unknown case: {name}")


def control_invariant(name: str, case: dict[str, Any]) -> tuple[bool, str]:
    if name.startswith("missing-"):
        return aborted(case), "untreated missing-DRBG control must terminate with SIGABRT"
    if name == "secure-heap-workers":
        return aborted(case) or started(case), "control may terminate with SIGABRT or complete; timeout and other crashes fail"
    return candidate_invariant(name, case)


def expectation(candidate: dict[str, Any], control: dict[str, Any] | None) -> dict[str, Any]:
    name = candidate["name"]
    candidate_ok, candidate_reason = candidate_invariant(name, candidate)
    control_verdict: dict[str, Any] | None = None
    if control is not None:
        control_ok, control_reason = control_invariant(name, control)
        control_verdict = {"ok": control_ok, "reason": control_reason}

    difference = None
    if control is not None and name.startswith("missing-") and name.endswith("-startup"):
        difference = {"expected": "control SIGABRT; candidate starts", "observed": aborted(control) and started(candidate), "required": True}
    elif control is not None and name.startswith("missing-") and name.endswith("-crypto"):
        difference = {"expected": "control SIGABRT; candidate reports a first-crypto error", "observed": aborted(control) and failed_without_abort(candidate), "required": True}
    elif control is not None and name == "secure-heap-workers":
        difference = {"expected": "control can SIGABRT; candidate exits after worker-local results", "observed": aborted(control) and started(candidate), "required": False}

    return {
        "candidate_invariant": {"ok": candidate_ok, "reason": candidate_reason},
        "control_invariant": control_verdict,
        "disclosed_difference": difference,
    }


def cases(fips_node_args: list[str]) -> list[tuple[str, str, list[str], dict[str, str]]]:
    base = str(BASE_ONLY)
    missing = str(RANDOM_UNAVAILABLE)
    result = [
        ("default", "default", [], {}),
        ("legacy", "default", ["--openssl-legacy-provider"], {}),
        ("fips-request", "fips", ["--enable-fips"], {}),
        ("base-cli", "default", [f"--openssl-config={base}"], {}),
        ("base-env", "default", [], {"OPENSSL_CONF": base}),
        ("missing-cli-startup", "startup", [f"--openssl-config={missing}"], {}),
        ("missing-env-startup", "startup", [], {"OPENSSL_CONF": missing}),
        ("missing-cli-crypto", "default", [f"--openssl-config={missing}"], {}),
        ("missing-env-crypto", "default", [], {"OPENSSL_CONF": missing}),
        ("secure-heap-workers", "workers", ["--secure-heap=1024", "--secure-heap-min=4"], {}),
        ("first-crypto", "default", [], {}),
        ("throughput", "throughput", [], {}),
    ]
    if fips_node_args:
        result.append(("fips-configured-startup", "fips", fips_node_args, {}))
    return result


def persist(report: dict[str, Any], output: Path | None) -> None:
    if output is not None:
        output.write_text(f"{json.dumps(report, indent=2, sort_keys=True)}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True, help="Patched native Node binary")
    parser.add_argument("--control", type=Path, help="Same-revision pristine native Node binary")
    parser.add_argument("--timeout", type=float, default=15, help="Per-process timeout in seconds")
    parser.add_argument("--iterations", type=int, default=5000, help="randomBytes calls in throughput mode")
    parser.add_argument(
        "--fips-node-arg",
        action="append",
        default=[],
        help="Node argument for a configured FIPS startup check; repeat as needed",
    )
    parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    args = parser.parse_args()
    for binary in (args.candidate, args.control):
        if binary is not None and (not binary.is_file() or not os.access(binary, os.X_OK)):
            parser.error(f"not an executable file: {binary}")
    if args.output is not None and args.output.exists():
        parser.error(f"refusing to overwrite existing report: {args.output}")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "schema": 1,
        "platform": sys.platform,
        "candidate": native_binary(args.candidate),
        "control": native_binary(args.control) if args.control else None,
        "timeout_seconds": args.timeout,
        "cases": [],
        "complete": False,
    }
    candidate_failures: list[str] = []
    control_failures: list[str] = []
    difference_failures: list[str] = []
    persist(report, args.output)
    for name, mode, node_args, env in cases(args.fips_node_arg):
        candidate = run_case(args.candidate, name, mode, node_args, env, args.timeout, args.iterations)
        control = run_case(args.control, name, mode, node_args, env, args.timeout, args.iterations) if args.control else None
        verdict = expectation(candidate, control)
        report["cases"].append({"candidate": candidate, "control": control, "verdict": verdict})
        if not verdict["candidate_invariant"]["ok"]:
            candidate_failures.append(name)
        if verdict["control_invariant"] is not None and not verdict["control_invariant"]["ok"]:
            control_failures.append(name)
        difference = verdict["disclosed_difference"]
        if difference is not None and difference["required"] and not difference["observed"]:
            difference_failures.append(name)
        report["candidate_failures"] = candidate_failures
        report["control_failures"] = control_failures
        report["difference_failures"] = difference_failures
        report["strict_pass"] = not candidate_failures and not control_failures
        report["differential_pass"] = report["strict_pass"] and not difference_failures
        persist(report, args.output)
    report["complete"] = True
    report["candidate_failures"] = candidate_failures
    report["control_failures"] = control_failures
    report["difference_failures"] = difference_failures
    report["strict_pass"] = not candidate_failures and not control_failures
    report["differential_pass"] = report["strict_pass"] and not difference_failures
    serialized = json.dumps(report, indent=2, sort_keys=True)
    persist(report, args.output)
    print(serialized)
    return 0 if report["differential_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
