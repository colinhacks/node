#!/usr/bin/env python3
"""Prepare and exercise a local OpenSSL 3 FIPS provider without rebuilding Node."""

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


MODULE_NAME = "libopenssl-fipsmodule.so"
FIPS_PROVIDER_NAME = "libopenssl-fipsmodule"

FIPS_SMOKE = r'''
const crypto = require('node:crypto');
const random = crypto.randomBytes(16);
const sha256 = crypto.createHash('sha256').update('abc').digest('hex');
let md5;
try {
  crypto.createHash('md5').update(random).digest('hex');
  md5 = { available: true };
} catch (error) {
  md5 = { available: false, code: error.code ?? null, message: error.message };
}
const result = { fips: crypto.getFips(), randomBytes: random.length, sha256, md5 };
if (result.fips !== 1 || result.randomBytes !== 16 || result.sha256 !== 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad' || result.md5.available) {
  throw new Error(`unexpected FIPS smoke result: ${JSON.stringify(result)}`);
}
process.stdout.write(`${JSON.stringify(result)}\n`);
'''


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def node_cc(source: Path) -> Path:
    path = source / "src" / "node.cc"
    if not path.is_file():
        raise ValueError(f"not a Node source directory: {source}")
    return path


def source_identity(source: Path) -> dict[str, str]:
    return {"path": str(source.resolve()), "node_cc_sha256": sha256(node_cc(source))}


def assert_source_unchanged(source: Path, manifest: dict[str, Any]) -> str:
    current = sha256(node_cc(source))
    expected = manifest["source"]["node_cc_sha256"]
    if current != expected:
        raise RuntimeError(f"source src/node.cc changed: expected {expected}, found {current}")
    return current


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(f"{json.dumps(value, indent=2, sort_keys=True)}\n")


def run_logged(command: list[str], *, environment: dict[str, str], log: Path, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    with log.open("x") as output:
        output.write(f"{json.dumps({'command': command}, sort_keys=True)}\n\n--- combined output ---\n")
        output.flush()
        timed_out = False
        launch_error = None
        try:
            process = subprocess.Popen(
                command,
                text=True,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=environment,
                start_new_session=True,
            )
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                returncode = process.wait()
        except OSError as error:
            launch_error = str(error)
            returncode = 127
        record = {
            "command": command,
            "returncode": returncode,
            "timed_out": timed_out,
            "elapsed_ms": (time.monotonic() - started) * 1000,
            "ok": returncode == 0 and not timed_out and launch_error is None,
        }
        if launch_error is not None:
            record["launch_error"] = launch_error
        output.write(f"\n--- result ---\n{json.dumps(record, sort_keys=True)}\n")
    record["log"] = str(log)
    return record


def clean_node_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith("NODE_") or key.startswith("__NUB_"):
            environment.pop(key)
    for key in ("OPENSSL_CONF", "LLVM_PROFILE_FILE"):
        environment.pop(key, None)
    environment["LC_ALL"] = "C"
    return environment


def build_paths(source: Path) -> tuple[Path, Path, list[Path]]:
    release = source / "out" / "Release"
    return release, release / "openssl-cli", [
        release / MODULE_NAME,
        release / "lib" / MODULE_NAME,
        release / "obj.target" / "deps" / "openssl" / MODULE_NAME,
    ]


def find_module(candidates: list[Path]) -> Path:
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    choices = ", ".join(str(candidate) for candidate in candidates)
    raise RuntimeError(f"FIPS module target completed but no module was found: {choices}")


def fips_config(fips_module_config: Path, module: Path) -> str:
    return f"""nodejs_conf = nodejs_init
config_diagnostics = 1

.include {fips_module_config}

[nodejs_init]
providers = provider_sect

[provider_sect]
fips = fips_sect
base = base_sect

[fips_sect]
activate = 1
module = {module}

[base_sect]
activate = 1
"""


def parse_json_line(log_contents: str) -> dict[str, Any] | None:
    _, marker, output = log_contents.partition("--- combined output ---\n")
    if not marker:
        return None
    output, _, _ = output.partition("\n--- result ---")
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def phase_build(args: argparse.Namespace) -> int:
    source = args.source.resolve()
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"refusing to overwrite existing output directory: {output}")
    release, openssl_cli, module_candidates = build_paths(source)
    if not (release / "build.ninja").is_file():
        raise ValueError(f"missing default Ninja configuration: {release / 'build.ninja'}")
    node_binary = release / "node"
    if not node_binary.is_file():
        raise ValueError(f"missing existing Node binary; refusing a build that could rebuild it: {node_binary}")
    output.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "schema": 1,
        "source": source_identity(source),
        "node_binary": {"path": str(node_binary.resolve()), "sha256_before": sha256(node_binary)},
        "build": {"release": str(release), "targets": ["openssl-fipsmodule", "openssl-cli"], "complete": False},
        "complete": False,
    }
    write_json(output / "manifest.json", manifest)
    command = ["ninja", "-C", str(release), "openssl-fipsmodule", "openssl-cli"]
    if args.jobs is not None:
        command[1:1] = ["-j", str(args.jobs)]
    build = run_logged(command, environment=os.environ.copy(), log=output / "build.log", timeout=args.timeout)
    build["source_node_cc_sha256_after"] = assert_source_unchanged(source, manifest)
    manifest["node_binary"]["sha256_after"] = sha256(node_binary)
    manifest["node_binary"]["unchanged"] = manifest["node_binary"]["sha256_before"] == manifest["node_binary"]["sha256_after"]
    manifest["build"].update(build)
    if build["ok"] and manifest["node_binary"]["unchanged"]:
        try:
            module = find_module(module_candidates)
            if not openssl_cli.is_file():
                raise RuntimeError(f"Ninja completed without openssl-cli: {openssl_cli}")
            manifest["module"] = {"path": str(module), "sha256": sha256(module)}
            manifest["openssl_cli"] = {"path": str(openssl_cli.resolve()), "sha256": sha256(openssl_cli)}
            manifest["build"]["complete"] = True
        except RuntimeError as error:
            manifest["build"]["output_error"] = str(error)
            write_json(output / "manifest.json", manifest)
            return 1
    elif build["ok"]:
        manifest["build"]["output_error"] = "existing Node binary changed during the OpenSSL-only build"
    write_json(output / "manifest.json", manifest)
    return 0 if manifest["build"].get("complete") else 2


def load_manifest(source: Path, output: Path) -> tuple[Path, dict[str, Any]]:
    path = output / "manifest.json"
    if not path.is_file():
        raise ValueError(f"missing build manifest: {path}")
    manifest = json.loads(path.read_text())
    if manifest.get("source", {}).get("path") != str(source.resolve()):
        raise ValueError("source path does not match the build manifest")
    assert_source_unchanged(source, manifest)
    return path, manifest


def phase_install(args: argparse.Namespace) -> int:
    source = args.source.resolve()
    output = args.output.resolve()
    manifest_path, manifest = load_manifest(source, output)
    if not manifest.get("build", {}).get("complete"):
        raise ValueError("build phase did not produce an OpenSSL CLI and FIPS module")
    fips_module_config = output / "fipsmodule.cnf"
    external_config = output / "openssl-fips.cnf"
    log = output / "fipsinstall.log"
    for path in (fips_module_config, external_config, log):
        if path.exists():
            raise ValueError(f"refusing to overwrite existing install output: {path}")
    module = Path(manifest["module"]["path"])
    openssl_cli = Path(manifest["openssl_cli"]["path"])
    if sha256(module) != manifest["module"]["sha256"] or sha256(openssl_cli) != manifest["openssl_cli"]["sha256"]:
        raise RuntimeError("module or OpenSSL CLI changed after the build phase")
    environment = os.environ.copy()
    environment["OPENSSL_CONF"] = "/dev/null"
    environment["OPENSSL_MODULES"] = str(module.parent)
    command = [
        str(openssl_cli), "fipsinstall", "-provider_name", FIPS_PROVIDER_NAME,
        "-module", str(module), "-out", str(fips_module_config),
    ]
    manifest["install"] = {"complete": False, "command": command, "log": str(log)}
    write_json(manifest_path, manifest)
    install = run_logged(command, environment=environment, log=log, timeout=args.timeout)
    install["source_node_cc_sha256_after"] = assert_source_unchanged(source, manifest)
    manifest["install"] = install
    if install["ok"] and fips_module_config.is_file():
        external_config.write_text(fips_config(fips_module_config.resolve(), module.resolve()))
        manifest["fips_module_config"] = {"path": str(fips_module_config.resolve()), "sha256": sha256(fips_module_config)}
        manifest["external_config"] = {"path": str(external_config.resolve()), "sha256": sha256(external_config)}
        manifest["fips_node_args"] = ["--enable-fips", f"--openssl-config={external_config.resolve()}"]
        manifest["force_fips_node_args"] = ["--force-fips", f"--openssl-config={external_config.resolve()}"]
        manifest["install"]["complete"] = True
    write_json(manifest_path, manifest)
    return 0 if manifest["install"].get("complete") else 2


def phase_verify(args: argparse.Namespace) -> int:
    source = args.source.resolve()
    output = args.output.resolve()
    manifest_path, manifest = load_manifest(source, output)
    if not manifest.get("install", {}).get("complete"):
        raise ValueError("install phase did not produce a usable external configuration")
    config = Path(manifest["external_config"]["path"])
    if sha256(config) != manifest["external_config"]["sha256"]:
        raise RuntimeError("external FIPS configuration changed after installation")
    result: list[dict[str, Any]] = []
    manifest["verify"] = {"complete": False, "binaries": result}
    write_json(manifest_path, manifest)
    for binary in args.node:
        binary = binary.resolve()
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError(f"not an executable Node binary: {binary}")
        binary_before = sha256(binary)
        binary_result: dict[str, Any] = {"path": str(binary), "sha256_before": binary_before, "flags": []}
        for flag in ("--enable-fips", "--force-fips"):
            command = [str(binary), f"--openssl-config={config}", flag, "-e", FIPS_SMOKE]
            per_flag_log = output / f"verify-{binary.name}-{flag.removeprefix('--')}.log"
            if per_flag_log.exists():
                raise ValueError(f"refusing to overwrite existing verification log: {per_flag_log}")
            execution = run_logged(command, environment=clean_node_environment(), log=per_flag_log, timeout=args.timeout)
            payload = parse_json_line(per_flag_log.read_text())
            execution["payload"] = payload
            execution["ok"] = execution["ok"] and payload is not None and payload.get("fips") == 1 and payload.get("randomBytes") == 16 and payload.get("sha256") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" and payload.get("md5", {}).get("available") is False
            binary_result["flags"].append({"flag": flag, **execution})
            manifest["verify"]["binaries"] = result + [binary_result]
            write_json(manifest_path, manifest)
        binary_result["sha256_after"] = sha256(binary)
        binary_result["unchanged"] = binary_result["sha256_after"] == binary_before
        if not binary_result["unchanged"]:
            for execution in binary_result["flags"]:
                execution["ok"] = False
        result.append(binary_result)
    manifest["verify"] = {"source_node_cc_sha256_after": assert_source_unchanged(source, manifest), "binaries": result}
    manifest["complete"] = all(item["ok"] for binary in result for item in binary["flags"])
    write_json(manifest_path, manifest)
    return 0 if manifest["complete"] else 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="phase", required=True)
    for name in ("build", "install", "verify"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--source", type=Path, required=True, help="Existing configured Node source tree")
        subparser.add_argument("--output", type=Path, required=True, help="New evidence directory for this source tree")
        subparser.add_argument("--timeout", type=float, default=900, help="Per-command timeout in seconds")
        if name == "build":
            subparser.add_argument("--jobs", type=int, help="Ninja parallelism")
        if name == "verify":
            subparser.add_argument("--node", type=Path, action="append", required=True, help="Frozen Node binary to exercise; repeat for the entropy candidate")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.phase == "build":
            return phase_build(args)
        if args.phase == "install":
            return phase_install(args)
        return phase_verify(args)
    except (RuntimeError, ValueError) as error:
        print(f"fips-provider: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
