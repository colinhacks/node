#!/usr/bin/env python3
"""Train an instrumented Node artifact; these timings are not benchmarks."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from startup_lab import (DEFAULT_WORKLOADS, WORKLOADS, Workload, direct_path,
                         prepare_output, run_once, sanitized_environment, sha256)


def training_scripts(source):
    scripts = sorted((source / "tools/pgo").glob("pgo-*.js"))
    scripts = [path for path in scripts if path.name != "pgo-run-all.js"]
    if not scripts:
        raise ValueError("no Node PGO training scripts found")
    return scripts


def merge_profiles(tool, inputs, output, *, temporal=False):
    if not inputs or any(not path.is_file() or path.stat().st_size == 0
                         for path in inputs):
        raise ValueError("require nonempty raw profiles before merging")
    command = [tool, "merge", "-o", str(output), *map(str, inputs)]
    if temporal:
        command[2:2] = ["--temporal-profile-trace-reservoir-size=10000",
                        "--temporal-profile-max-trace-length=10000"]
    result = subprocess.run(command, capture_output=True, text=True,
                            timeout=120, check=False)
    if result.returncode or not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"profile merge failed: {result.stderr}")
    return {"command": command, "exit": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr,
            "output": str(output), "sha256": sha256(str(output))}


def archive_profile(path):
    """Retain a verified lossless raw profile without its mostly-zero disk cost."""
    record = {"raw_path": str(path), "raw_bytes": path.stat().st_size,
              "raw_sha256": sha256(str(path))}
    compressed = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as source, compressed.open("xb") as target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as stream:
            shutil.copyfileobj(source, stream)
    restored = hashlib.sha256()
    with gzip.open(compressed, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            restored.update(chunk)
    if restored.hexdigest() != record["raw_sha256"]:
        raise RuntimeError(f"raw profile archive verification failed: {path}")
    record.update(path=str(compressed), bytes=compressed.stat().st_size,
                  sha256=sha256(str(compressed)), compression="gzip")
    path.unlink()
    return record


def train(node, source, tool, output, duration, startup_rounds, *, temporal=False):
    if duration <= 0 or startup_rounds < 1:
        raise ValueError("duration and startup rounds must be positive")
    source = source.resolve(strict=True)
    scripts = training_scripts(source)
    output = prepare_output(output)
    environment, removed = sanitized_environment("system")
    environment.pop("STARTUP_LAB_READY_FD", None)
    report = {
        "node": node, "node_sha256": sha256(node), "source": str(source),
        "llvm_profdata": tool, "llvm_profdata_sha256": sha256(tool),
        "duration_seconds": duration, "startup_rounds": startup_rounds,
        "profile_mode": "temporal-per-process" if temporal else "online-merge",
        "temporal_merge_limits": ({"reservoir_size": 10000,
                                    "max_trace_length": 10000} if temporal else None),
        "timezone": "system", "removed_environment_names": sorted(removed),
        "trainer_sha256": sha256(__file__),
        "training_script_sha256": {str(p): sha256(str(p)) for p in scripts},
        "fixture_sha256": {str(p): sha256(str(p)) for p in
                           (Path(__file__).parent / "fixtures").iterdir()
                           if p.is_file()},
        "status": "running", "completed": {"throughput": 0, "startup": 0},
        "profiles": [], "merges": [],
    }

    def checkpoint():
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    checkpoint()
    try:
        with (output / "training.jsonl").open("x") as log:
            for phase in ("throughput", "startup"):
                raw_dir = output / "raw" / phase
                raw_dir.mkdir(parents=True)
                env = dict(environment,
                           LLVM_PROFILE_FILE=str(raw_dir / "%m.profraw"),
                           PGO_TRAINING_DURATION=str(round(duration * 1000)))
                if phase == "throughput":
                    cases = [Workload(p.stem, (str(p),), False) for p in scripts]
                else:
                    cases = [WORKLOADS[name] for _ in range(startup_rounds)
                             for name in DEFAULT_WORKLOADS]
                for index, workload in enumerate(cases):
                    if temporal:
                        # Temporal profiles cannot merge in the runtime. The case
                        # index also prevents collisions if a PID is later reused.
                        env["LLVM_PROFILE_FILE"] = str(
                            raw_dir / f"case-{index:05d}-%p.profraw")
                    result = run_once(node, workload, env,
                                      max(60, duration + 45))
                    log.write(json.dumps(dict(phase=phase, index=index,
                                              workload=workload.name,
                                              args=workload.args, **result)) + "\n")
                    log.flush()
                    if (result["status"] != "ok" or
                            "LLVM Profile Error:" in result["stderr"]):
                        raise RuntimeError(f"{phase}/{workload.name} failed: {result}")
                    if temporal:
                        written = list(raw_dir.glob(f"case-{index:05d}-*.profraw"))
                        if not written or any(p.stat().st_size == 0 for p in written):
                            raise RuntimeError(f"{phase}/{workload.name} wrote no profile")
                    report["completed"][phase] += 1
                    checkpoint()
                profiles = sorted(raw_dir.glob("*.profraw"))
                merge_options = {"temporal": True} if temporal else {}
                report["merges"].append(merge_profiles(
                    tool, profiles, output / f"{phase}.profdata", **merge_options))
                for profile in profiles:
                    if temporal:
                        report["profiles"].append(archive_profile(profile))
                    else:
                        report["profiles"].append({"path": str(profile),
                            "bytes": profile.stat().st_size,
                            "sha256": sha256(str(profile))})
                print(f"{phase}: {len(cases)} passed, {len(profiles)} profiles",
                      flush=True)
                checkpoint()
        report["merges"].append(merge_profiles(
            tool, [output / "throughput.profdata", output / "startup.profdata"],
            output / "node.profdata", **merge_options))
        report["status"] = "ok"
        checkpoint()
        return report
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = str(error)
        checkpoint()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True, type=direct_path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--llvm-profdata", required=True, type=direct_path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--duration", type=float, default=15)
    parser.add_argument("--startup-rounds", type=int, default=100)
    parser.add_argument("--temporal", action="store_true",
                        help="Keep separate process profiles; disable runtime merging")
    args = parser.parse_args()
    train(args.node, args.source, args.llvm_profdata, args.output,
          args.duration, args.startup_rounds, temporal=args.temporal)


if __name__ == "__main__":
    main()
