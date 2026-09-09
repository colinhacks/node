import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pgo_train


class PgoTrainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "node"
        (self.source / "tools/pgo").mkdir(parents=True)
        (self.source / "tools/pgo/pgo-example.js").write_text("// workload\n")
        (self.source / "tools/pgo/pgo-run-all.js").write_text("// driver\n")
        self.binary = self.root / "binary"
        self.binary.write_text("binary")

    def test_training_selection_excludes_driver(self):
        self.assertEqual([p.name for p in pgo_train.training_scripts(self.source)],
                         ["pgo-example.js"])

    def test_empty_training_selection_rejected(self):
        with self.assertRaisesRegex(ValueError, "no Node PGO"):
            pgo_train.training_scripts(self.root / "missing")

    def test_merge_requires_profiles(self):
        with patch.object(pgo_train.subprocess, "run") as run:
            for paths in ([], [self.root / "missing"]):
                with self.assertRaises(ValueError):
                    pgo_train.merge_profiles("tool", paths, self.root / "out")
            run.assert_not_called()

    def test_failure_is_recorded_and_not_merged(self):
        output = self.root / "output"
        with patch.object(pgo_train, "run_once", return_value={
                "status": "error", "stderr": "deliberate failure"}), \
                patch.object(pgo_train, "merge_profiles") as merge:
            with self.assertRaisesRegex(RuntimeError, "throughput/pgo-example"):
                pgo_train.train(str(self.binary), self.source, str(self.binary),
                                output, 1, 1)
            merge.assert_not_called()
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["completed"]["throughput"], 0)

    def test_success_covers_both_phases_with_isolated_profiles(self):
        output = self.root / "output"
        seen = []

        def run(node, workload, env, timeout):
            path = Path(env["LLVM_PROFILE_FILE"].replace("%m", "module"))
            path.write_bytes(b"profile")
            seen.append((workload.name, path.parent.name))
            self.assertNotIn("NODE_SECRET", env)
            self.assertNotIn("TZ", env)
            self.assertNotIn("STARTUP_LAB_READY_FD", env)
            return {"status": "ok", "stderr": ""}

        def merge(tool, inputs, output):
            output.write_bytes(b"merged")
            return {"output": str(output)}

        with patch.dict("os.environ", {"NODE_SECRET": "hidden", "TZ": "UTC",
                                       "STARTUP_LAB_READY_FD": "999"}), \
                patch.object(pgo_train, "run_once", side_effect=run), \
                patch.object(pgo_train, "merge_profiles", side_effect=merge):
            report = pgo_train.train(str(self.binary), self.source,
                                     str(self.binary), output, 1, 2)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["completed"], {"throughput": 1, "startup": 16})
        self.assertEqual(len(report["merges"]), 3)
        self.assertEqual(seen[0], ("pgo-example", "throughput"))
        self.assertEqual({name for name, phase in seen if phase == "startup"},
                         set(pgo_train.DEFAULT_WORKLOADS))
        self.assertNotIn("hidden", (output / "report.json").read_text())

    def test_archive_is_lossless_and_keeps_raw_identity(self):
        raw = self.root / "sample.profraw"
        content = b"profile\x00" * 1000
        raw.write_bytes(content)
        record = pgo_train.archive_profile(raw)
        self.assertFalse(raw.exists())
        self.assertEqual(gzip.decompress(Path(record["path"]).read_bytes()), content)
        self.assertEqual(record["raw_sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(record["raw_bytes"], len(content))
        self.assertLess(record["bytes"], len(content))

    def test_temporal_profiles_do_not_merge_online_or_reuse_case_paths(self):
        output = self.root / "temporal"
        paths = []

        def run(node, workload, env, timeout):
            self.assertNotIn("%m", env["LLVM_PROFILE_FILE"])
            # A repeated PID must still produce a distinct path for every case.
            path = Path(env["LLVM_PROFILE_FILE"].replace("%p", "123"))
            self.assertNotIn(path, paths)
            path.write_bytes(b"raw profile")
            paths.append(path)
            return {"status": "ok", "stderr": ""}

        def merge(tool, inputs, output, *, temporal=False):
            self.assertTrue(temporal)
            self.assertTrue(all(path.is_file() for path in inputs))
            output.write_bytes(b"merged")
            return {"output": str(output)}

        with patch.object(pgo_train, "run_once", side_effect=run), \
                patch.object(pgo_train, "merge_profiles", side_effect=merge):
            report = pgo_train.train(str(self.binary), self.source,
                                     str(self.binary), output, 1, 2, temporal=True)
        self.assertEqual(report["profile_mode"], "temporal-per-process")
        self.assertEqual(report["completed"], {"throughput": 1, "startup": 16})
        self.assertEqual(len(report["profiles"]), 17)
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertTrue(all(Path(p["path"]).is_file() for p in report["profiles"]))

    def test_temporal_missing_profile_is_not_counted(self):
        output = self.root / "missing-profile"
        with patch.object(pgo_train, "run_once", return_value={
                "status": "ok", "stderr": ""}), \
                patch.object(pgo_train, "merge_profiles") as merge:
            with self.assertRaisesRegex(RuntimeError, "wrote no profile"):
                pgo_train.train(str(self.binary), self.source, str(self.binary),
                                output, 1, 1, temporal=True)
            merge.assert_not_called()
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["completed"]["throughput"], 0)

    def test_temporal_merge_limits_are_explicit(self):
        raw = self.root / "raw.profraw"
        raw.write_bytes(b"raw")
        output = self.root / "merged.profdata"

        def merge(argv, **kwargs):
            self.assertIn("--temporal-profile-trace-reservoir-size=10000", argv)
            self.assertIn("--temporal-profile-max-trace-length=10000", argv)
            output.write_bytes(b"merged")
            from subprocess import CompletedProcess
            return CompletedProcess(argv, 0, "", "")

        with patch.object(pgo_train.subprocess, "run", side_effect=merge):
            pgo_train.merge_profiles("tool", [raw], output, temporal=True)


if __name__ == "__main__":
    unittest.main()
