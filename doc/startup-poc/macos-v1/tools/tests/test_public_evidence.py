import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_evidence


class PublicEvidenceTests(unittest.TestCase):
    def test_compressed_hash_verification_and_corruption_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decoded = b'{"value": 1.25}\n'
            published = gzip.compress(decoded, mtime=0)
            payload = root / "payload.json.gz"
            payload.write_bytes(published)
            (root / "evidence").mkdir()
            (root / "evidence/index.json").write_text("[]")
            (root / "MANIFEST.json").write_text(json.dumps({"files": [{
                "path": payload.name,
                "published_sha256": hashlib.sha256(published).hexdigest(),
                "decoded_sha256": hashlib.sha256(decoded).hexdigest(),
            }]}))
            with patch.object(verify_evidence, "ROOT", root):
                with contextlib.redirect_stdout(io.StringIO()):
                    verify_evidence.verify()
                payload.write_bytes(published + b"changed")
                with self.assertRaisesRegex(ValueError, "published hash mismatch"):
                    verify_evidence.verify()

    def test_clean_wrapper_removes_runtime_variables(self):
        wrapper = Path(__file__).resolve().parents[1] / "clean_env.py"
        environment = dict(os.environ, NODE_OPTIONS="test-value",
                           __NUB_TEST="test-value", BUN_OPTIONS="test-value",
                           STARTUP_PUBLIC_TEST="preserved")
        program = ("import os; assert 'NODE_OPTIONS' not in os.environ; "
                   "assert '__NUB_TEST' not in os.environ; "
                   "assert 'BUN_OPTIONS' not in os.environ; "
                   "assert os.environ['STARTUP_PUBLIC_TEST'] == 'preserved'")
        result = subprocess.run([sys.executable, str(wrapper), sys.executable,
                                 "-c", program], env=environment,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
