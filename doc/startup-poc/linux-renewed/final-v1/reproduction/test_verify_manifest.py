import gzip
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE = Path(__file__).with_name("verify_manifest.py")
SPEC = importlib.util.spec_from_file_location("verify_manifest", MODULE)
verify_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_manifest)


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


class VerifyManifestTest(unittest.TestCase):
    def make_root(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        raw = b"public evidence\n"
        (root / "raw.txt").write_bytes(raw)
        compressed = gzip.compress(raw)
        (root / "raw.txt.gz").write_bytes(compressed)
        entries = {
            "raw.txt": {"bytes": len(raw), "sha256": sha256(raw)},
            "raw.txt.gz": {"bytes": len(compressed), "sha256": sha256(compressed), "uncompressed_sha256": sha256(raw)},
        }
        (root / "manifest.json").write_text(json.dumps(entries))
        return temp, root

    def test_accepts_complete_payload(self):
        temp, root = self.make_root()
        with temp:
            verify_manifest.verify(root)

    def test_rejects_missing_payload(self):
        temp, root = self.make_root()
        with temp:
            (root / "raw.txt").unlink()
            with self.assertRaisesRegex(AssertionError, "missing manifest payload"):
                verify_manifest.verify(root)

    def test_includes_nested_manifest(self):
        temp, root = self.make_root()
        with temp:
            nested = root / 'source-package' / 'manifest.json'
            nested.parent.mkdir()
            raw = b'{"source": "identity"}'
            nested.write_bytes(raw)
            manifest = root / 'manifest.json'
            entries = json.loads(manifest.read_text())
            entries['source-package/manifest.json'] = {'bytes': len(raw), 'sha256': sha256(raw)}
            manifest.write_text(json.dumps(entries))
            verify_manifest.verify(root)

    def test_rejects_unlisted_symlink(self):
        temp, root = self.make_root()
        with temp:
            (root / 'alias').symlink_to(root / 'raw.txt')
            with self.assertRaisesRegex(AssertionError, 'symlink in package'):
                verify_manifest.verify(root)

    def test_rejects_unlisted_payload(self):
        temp, root = self.make_root()
        with temp:
            (root / "extra.txt").write_text("not declared")
            with self.assertRaisesRegex(AssertionError, "file coverage differs"):
                verify_manifest.verify(root)

    def test_rejects_digest_corruption(self):
        temp, root = self.make_root()
        with temp:
            (root / "raw.txt").write_bytes(b"broken evidence\n")
            with self.assertRaisesRegex(AssertionError, "SHA-256 mismatch"):
                verify_manifest.verify(root)

    def test_rejects_traversal(self):
        temp, root = self.make_root()
        with temp:
            (root / "manifest.json").write_text(json.dumps({"../outside": {"bytes": 0, "sha256": sha256(b"")}}))
            with self.assertRaisesRegex(AssertionError, "unsafe manifest path"):
                verify_manifest.verify(root)
