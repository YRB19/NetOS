import tempfile
import unittest
from pathlib import Path

from shared.versioning.content_hash import (
    data_snapshot_version,
    hash_bytes,
    hash_file,
    hash_json_stable,
)


class TestHashBytes(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(hash_bytes(b"abc"), hash_bytes(b"abc"))

    def test_sensitive_to_content(self):
        self.assertNotEqual(hash_bytes(b"abc"), hash_bytes(b"abd"))


class TestHashFile(unittest.TestCase):
    def test_same_bytes_same_hash(self):
        with tempfile.TemporaryDirectory() as d:
            p1 = Path(d) / "a.csv"
            p2 = Path(d) / "b.csv"
            p1.write_text("x,y\n1,2\n")
            p2.write_text("x,y\n1,2\n")
            self.assertEqual(hash_file(p1), hash_file(p2))

    def test_different_bytes_different_hash(self):
        with tempfile.TemporaryDirectory() as d:
            p1 = Path(d) / "a.csv"
            p2 = Path(d) / "b.csv"
            p1.write_text("x,y\n1,2\n")
            p2.write_text("x,y\n1,3\n")
            self.assertNotEqual(hash_file(p1), hash_file(p2))


class TestHashJsonStable(unittest.TestCase):
    def test_key_order_does_not_matter(self):
        h1 = hash_json_stable({"a": 1, "b": 2})
        h2 = hash_json_stable({"b": 2, "a": 1})
        self.assertEqual(h1, h2)

    def test_content_change_changes_hash(self):
        h1 = hash_json_stable({"a": 1})
        h2 = hash_json_stable({"a": 2})
        self.assertNotEqual(h1, h2)


class TestDataSnapshotVersion(unittest.TestCase):
    def test_deterministic(self):
        v1 = data_snapshot_version("rawhash123", "norm_v1")
        v2 = data_snapshot_version("rawhash123", "norm_v1")
        self.assertEqual(v1, v2)

    def test_changes_with_raw_hash(self):
        v1 = data_snapshot_version("rawhash123", "norm_v1")
        v2 = data_snapshot_version("rawhash456", "norm_v1")
        self.assertNotEqual(v1, v2)

    def test_changes_with_normalization_version(self):
        v1 = data_snapshot_version("rawhash123", "norm_v1")
        v2 = data_snapshot_version("rawhash123", "norm_v2")
        self.assertNotEqual(v1, v2)

    def test_has_stable_prefix(self):
        v = data_snapshot_version("x", "y")
        self.assertTrue(v.startswith("snap_"))


if __name__ == "__main__":
    unittest.main()
