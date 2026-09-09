import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
RUNNER = LAB / "startup_lab.py"
MOCK = LAB / "tests" / "mock_runtime.py"
MISSING_MARKER = LAB / "tests" / "mock_missing_marker.py"
INVALID_MARKER = LAB / "tests" / "mock_invalid_marker.py"
CHILD_PIPE = LAB / "tests" / "mock_child_pipe.py"
ORPHAN_PIPE = LAB / "tests" / "mock_orphan_pipe.py"
LARGE_STDOUT = LAB / "tests" / "mock_large_stdout.py"
SPEC = importlib.util.spec_from_file_location("startup_lab", RUNNER)
STARTUP_LAB = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["startup_lab"] = STARTUP_LAB
SPEC.loader.exec_module(STARTUP_LAB)


class StartupLabTests(unittest.TestCase):
    def test_sanitizer_removes_all_node_options_without_mutating_parent(self):
        parent = {"NODE_OPTIONS": "--require preload.js", "NODE_USE_SYSTEM_CA": "1",
                  "NODE_FUTURE_OPTION": "enabled", "PATH": "/bin", "TZ": "Pacific/Honolulu"}
        with mock.patch.dict(STARTUP_LAB.os.environ, parent, clear=True):
            environment, removed = STARTUP_LAB.sanitized_environment()
            self.assertFalse(any(key.startswith("NODE_") for key in environment))
            self.assertEqual(environment["PATH"], "/bin")
            self.assertEqual(environment["TZ"], "UTC")
            self.assertEqual(dict(STARTUP_LAB.os.environ), parent)
        self.assertIn("NODE_USE_SYSTEM_CA", removed)
        self.assertIn("NODE_FUTURE_OPTION", removed)

    def test_sanitizer_does_not_record_arbitrary_node_credentials(self):
        with mock.patch.dict(STARTUP_LAB.os.environ, {"NODE_AUTH_TOKEN": "secret-value"}, clear=True):
            environment, removed = STARTUP_LAB.sanitized_environment()
        self.assertNotIn("NODE_AUTH_TOKEN", environment)
        self.assertEqual(removed["NODE_AUTH_TOKEN"], "<redacted>")
        self.assertNotIn("secret-value", json.dumps(removed))

    def test_sanitizer_removes_wrapper_bookkeeping_and_redacts_values(self):
        parent = {"__NUB_AUGMENTED_NODE_OPTIONS": "--require wrapper.cjs",
                  "__NUB_RUNTIME_CONFIG": "secret-value", "__NUB_FUTURE": "private",
                  "PRESERVE_ME": "yes"}
        with mock.patch.dict(STARTUP_LAB.os.environ, parent, clear=True):
            environment, removed = STARTUP_LAB.sanitized_environment("system")
            self.assertEqual(dict(STARTUP_LAB.os.environ), parent)
        self.assertFalse(any(key.startswith("__NUB_") for key in environment))
        self.assertEqual(environment["PRESERVE_ME"], "yes")
        for key in parent:
            if key.startswith("__NUB_"):
                self.assertEqual(removed[key], "<redacted>")
        self.assertNotIn("secret-value", json.dumps(removed))
        self.assertNotIn("wrapper.cjs", json.dumps(removed))

    def test_timezone_modes_remove_parent_tz_and_preserve_other_environment(self):
        parent = {"TZ": "America/Los_Angeles", "PRESERVE_ME": "yes"}
        with mock.patch.dict(os.environ, parent, clear=True):
            utc, _ = STARTUP_LAB.sanitized_environment()
            system, _ = STARTUP_LAB.sanitized_environment("system")
            self.assertEqual(dict(os.environ), parent)
        self.assertEqual(utc["TZ"], "UTC")
        self.assertNotIn("TZ", system)
        self.assertEqual(utc["PRESERVE_ME"], "yes")
        self.assertEqual(system["PRESERVE_ME"], "yes")

    def test_report_records_effective_timezone_policy(self):
        for mode, expected_override in (("utc", "UTC"), ("system", None)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "results"
                result = subprocess.run([sys.executable, str(RUNNER), "--node", str(MOCK), "--bun", str(MOCK), "--runs", "1", "--warmups", "0", "--workloads", "eval-empty", "--timezone", mode, "--output", str(output)], capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                policy = json.loads((output / "report.json").read_text())["environment_policy"]
                self.assertEqual(policy["timezone_mode"], mode)
                self.assertEqual(policy["timezone_override"], {"TZ": expected_override})

    def test_mock_runtimes_produce_raw_and_summary_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results"
            result = subprocess.run(
                [sys.executable, str(RUNNER), "--node", str(MOCK), "--baseline-node", str(MOCK), "--release-node", str(MOCK), "--bun", str(MOCK), "--runs", "2", "--warmups", "1", "--seed", "7", "--workloads", "eval-empty", "hello", "--output", str(output)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(report["seed"], 7)
            self.assertEqual(len((output / "raw.jsonl").read_text().splitlines()), 24)
            self.assertIn("baseline-node", report["runtimes"])
            self.assertIn("source_dirty", report["runtimes"]["baseline-node"]["source"])
            self.assertEqual(report["comparability"]["baseline_node_vs_fork_node"]["status"], "exploratory-not-verified-comparable")
            self.assertEqual(report["summaries"]["eval-empty"]["workload_ready_ms"]["paired_ratios"]["fork_node_over_bun"], None)
            comparison = report["summaries"]["hello"]["workload_ready_ms"]["paired_ratios"]["baseline_node_over_fork_node"]
            self.assertEqual(comparison["numerator_runtime"], "baseline-node")
            self.assertEqual(comparison["denominator_runtime"], "fork-node")

    def test_pairing_intersects_successful_round_ids(self):
        result = STARTUP_LAB.paired_ratio({0: 10.0, 1: 200.0}, {0: 5.0, 2: 1.0}, "baseline-node", "fork-node", 7)
        self.assertEqual(result["n"], 1)
        self.assertEqual(result["paired_rounds"], [0])
        self.assertEqual(result["median_ratio"], 2.0)

    def test_source_provenance_preserves_dirty_diff_before_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            subprocess.run(["/usr/bin/git", "init", "-q", str(source)], check=True)
            subprocess.run(["/usr/bin/git", "-C", str(source), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["/usr/bin/git", "-C", str(source), "config", "user.name", "Test"], check=True)
            tracked = source / "tracked.txt"
            tracked.write_text("before\n")
            subprocess.run(["/usr/bin/git", "-C", str(source), "add", "tracked.txt"], check=True)
            subprocess.run(["/usr/bin/git", "-C", str(source), "commit", "-qm", "initial"], check=True)
            tracked.write_text("after\n")
            provenance = STARTUP_LAB.source_provenance("baseline-node", source, Path(directory) / "output")
            self.assertTrue(provenance["source_dirty"])
            self.assertIn("tracked.txt", Path(provenance["source_diff_file"]).read_text())

    def test_runtime_must_be_an_absolute_executable(self):
        result = subprocess.run([sys.executable, str(RUNNER), "--node", "not-a-runtime", "--bun", str(MOCK)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime must be an executable absolute path", result.stderr)

    def test_ready_workloads_reject_missing_and_invalid_markers(self):
        workload = STARTUP_LAB.Workload("marker", (), True)
        missing = STARTUP_LAB.run_once(str(MISSING_MARKER), workload, {}, 1)
        invalid = STARTUP_LAB.run_once(str(INVALID_MARKER), workload, {}, 1)
        self.assertEqual(missing["status"], "marker-missing")
        self.assertEqual(invalid["status"], "marker-invalid")
        self.assertIsNone(missing["workload_ready_ms"])
        self.assertIn("invalid readiness marker", invalid["error"])

    def test_marker_failure_is_checkpointed_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results"
            result = subprocess.run([sys.executable, str(RUNNER), "--node", str(MISSING_MARKER), "--bun", str(MISSING_MARKER), "--runs", "1", "--warmups", "0", "--workloads", "hello", "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            samples = [json.loads(line) for line in (output / "raw.jsonl").read_text().splitlines()]
            self.assertEqual({sample["status"] for sample in samples}, {"marker-missing"})
            self.assertTrue((output / "report.json").is_file())

    def test_timeout_kills_process_group_with_inherited_pipe(self):
        started = time.monotonic()
        result = STARTUP_LAB.run_once(str(CHILD_PIPE), STARTUP_LAB.Workload("child", (), True), {}, 0.1)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(result["status"], "timeout")

    def test_exited_parent_with_pipe_holding_descendant_is_an_error(self):
        started = time.monotonic()
        result = STARTUP_LAB.run_once(str(ORPHAN_PIPE), STARTUP_LAB.Workload("orphan", (), True), {}, 1)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(result["status"], "cleanup-timeout")

    def test_nonempty_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results"
            output.mkdir()
            (output / "existing").write_text("evidence")
            result = subprocess.run([sys.executable, str(RUNNER), "--node", str(MOCK), "--bun", str(MOCK), "--output", str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("output directory must be empty", result.stderr)

    def test_config_normalization_and_comparability_require_modes_and_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.config"
            fork = root / "fork.config"
            baseline.write_text("{'target_defaults': {'default_configuration': 'Release', 'is_debug': 0, 'node_use_node_snapshot': 1}, 'prefix': '/baseline', 'feature': ['enabled']}\n")
            fork.write_text("{'target_defaults': {'default_configuration': 'Release', 'is_debug': 0, 'node_use_node_snapshot': 1}, 'prefix': '/fork', 'feature': ['enabled']}\n")
            baseline_metadata = STARTUP_LAB.config_metadata(baseline)
            self.assertEqual(baseline_metadata["normalized_config"], STARTUP_LAB.config_metadata(fork)["normalized_config"])
            self.assertEqual(STARTUP_LAB.build_characteristics(baseline_metadata), {"release_mode": "release", "snapshot": "1"})

    def test_only_cctest_source_lists_are_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, cctest_variant, feature_variant = root / "baseline", root / "cctest", root / "feature"
            baseline.write_text("{'variables': {'node_cctest_sources': ['test/cctest/a.cc'], 'v8_enable_maglev': 1, 'node_shared_libuv': 'false'}}")
            cctest_variant.write_text("{'variables': {'node_cctest_sources': ['test/cctest/b.cc'], 'v8_enable_maglev': 1, 'node_shared_libuv': 'false'}}")
            feature_variant.write_text("{'variables': {'node_cctest_sources': ['test/cctest/a.cc'], 'v8_enable_maglev': 0, 'node_shared_libuv': 'false'}}")
            baseline_config = STARTUP_LAB.config_metadata(baseline)
            self.assertEqual(baseline_config["normalized_config"], STARTUP_LAB.config_metadata(cctest_variant)["normalized_config"])
            self.assertNotEqual(baseline_config["normalized_config"], STARTUP_LAB.config_metadata(feature_variant)["normalized_config"])
            self.assertNotEqual(baseline_config["sha256"], STARTUP_LAB.config_metadata(cctest_variant)["sha256"])

    def test_build_manifest_validates_binary_and_optional_config_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, manifest_path = root / "config.gypi", root / "manifest.json"
            config_path.write_text("{'target_defaults': {'default_configuration': 'Release'}}")
            config = STARTUP_LAB.config_metadata(config_path)
            manifest_path.write_text(json.dumps({"schema": 1, "binary_sha256": STARTUP_LAB.sha256(str(MOCK)), "config_sha256": config["sha256"], "build_command": "./configure"}))
            valid = STARTUP_LAB.build_manifest_metadata(manifest_path, STARTUP_LAB.sha256(str(MOCK)), config)
            self.assertTrue(valid["validated"])
            self.assertEqual(valid["contents"]["schema"], 1)
            self.assertEqual(valid["sha256"], STARTUP_LAB.sha256(str(manifest_path)))
            manifest_path.write_text(json.dumps({"binary_sha256": "wrong", "config_sha256": config["sha256"]}))
            mismatch = STARTUP_LAB.build_manifest_metadata(manifest_path, STARTUP_LAB.sha256(str(MOCK)), config)
            self.assertFalse(mismatch["validated"])
            self.assertFalse(mismatch["binary_sha256_matches"])
            manifest_path.write_text(json.dumps({"binary_sha256": STARTUP_LAB.sha256(str(MOCK)), "config_sha256": "wrong"}))
            config_mismatch = STARTUP_LAB.build_manifest_metadata(manifest_path, STARTUP_LAB.sha256(str(MOCK)), config)
            self.assertFalse(config_mismatch["validated"])
            self.assertFalse(config_mismatch["config_sha256_matches"])

    def test_selector_drains_large_stdout_without_sleep_polling(self):
        result = STARTUP_LAB.run_once(str(LARGE_STDOUT), STARTUP_LAB.Workload("large", (), False), {}, 3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["stdout"]), 2 * 1024 * 1024)
        source = STARTUP_LAB.run_once.__code__.co_names
        self.assertNotIn("sleep", source)

    def test_unknown_architecture_cannot_be_verified_comparable(self):
        config = {"normalized_config": {"target_defaults": {"default_configuration": "Release", "node_use_node_snapshot": 1}}}
        metadata = {
            "baseline-node": {"path": "/artifacts/baseline", "binary_architecture": "cannot open", "build_config": config, "build_manifest": None, "build_characteristics": {"release_mode": "release", "snapshot": "1"}},
            "fork-node": {"path": "/artifacts/fork", "binary_architecture": "cannot open", "build_config": config, "build_manifest": None, "build_characteristics": {"release_mode": "release", "snapshot": "1"}},
        }
        result = STARTUP_LAB.node_comparability({"baseline-node": {}, "fork-node": {}}, metadata)
        self.assertEqual(result["status"], "exploratory-not-verified-comparable")
        self.assertFalse(result["checks"]["architecture_matches"])

    def test_selector_oserror_and_interrupt_cleanup_live_process_group(self):
        workload = STARTUP_LAB.Workload("child", (), True)
        with mock.patch.object(STARTUP_LAB.selectors.DefaultSelector, "select", side_effect=OSError("injected")):
            result = STARTUP_LAB.run_once(str(CHILD_PIPE), workload, {}, 1)
        self.assertEqual(result["status"], "launch-error")
        with mock.patch.object(STARTUP_LAB.selectors.DefaultSelector, "select", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                STARTUP_LAB.run_once(str(CHILD_PIPE), workload, {}, 1)


if __name__ == "__main__":
    unittest.main()
