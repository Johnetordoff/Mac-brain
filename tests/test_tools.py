import os
import tempfile
import unittest
from pathlib import Path

os.environ["MACBRAIN_HOME"] = tempfile.mkdtemp(prefix="macbrain-tools-")

from macbrain import db
from macbrain.tools import run_tool


def canonical(path) -> str:
    """Compare filesystem identities, not Darwin's /var vs /private/var spellings."""
    return str(Path(path).resolve())


class ToolTests(unittest.TestCase):
    def test_ai_can_propose_but_not_execute_cleanup(self):
        root = Path(tempfile.mkdtemp(prefix="macbrain-candidate-"))
        target = root / "old-cache"
        target.mkdir()
        (target / "x").write_text("data")
        result = run_tool("propose_cleanup", {
            "target": str(target),
            "title": "Old cache candidate",
            "evidence": "Known cache-like test directory with no active dependency in this test.",
            "expected_benefit": "Reclaim disk space.",
            "risk": "May need to be regenerated.",
        })
        self.assertTrue(target.exists())
        self.assertFalse(result["executed"])
        pid = int(result["proposal"].lstrip("P"))
        self.assertEqual(db.get_proposal(pid)["status"], "open")

    def test_storage_path_is_read_only(self):
        root = Path(tempfile.mkdtemp(prefix="macbrain-storage-"))
        child = root / "child"
        child.mkdir()
        (child / "blob").write_bytes(b"x" * 4096)
        rows = run_tool("storage_path", {"path": str(root), "limit": 10})
        self.assertTrue(child.exists())
        self.assertTrue(any(canonical(r["path"]) == canonical(child) for r in rows))

    def test_largest_files_is_read_only_and_bounded(self):
        root = Path(tempfile.mkdtemp(prefix="macbrain-largest-"))
        big = root / "big.bin"
        small = root / "small.bin"
        big.write_bytes(b"x" * (2 * 1024 * 1024))
        small.write_bytes(b"x")
        result = run_tool("largest_files", {"path": str(root), "min_mb": 1, "limit": 10, "max_entries": 1000})
        self.assertTrue(big.exists())
        self.assertEqual(canonical(result["files"][0]["path"]), canonical(big))

    def test_duplicate_large_files_requires_exact_hash_match(self):
        root = Path(tempfile.mkdtemp(prefix="macbrain-dupes-"))
        a = root / "a.bin"
        b = root / "b.bin"
        c = root / "c.bin"
        payload = b"a" * (1024 * 1024)
        a.write_bytes(payload)
        b.write_bytes(payload)
        c.write_bytes(b"b" * (1024 * 1024))
        result = run_tool("duplicate_large_files", {"path": str(root), "min_mb": 1, "max_entries": 1000, "max_hash_files": 10})
        groups = result["duplicate_groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(
            {canonical(p) for p in groups[0]["paths"]},
            {canonical(a), canonical(b)},
        )
        self.assertTrue(c.exists())


if __name__ == "__main__":
    unittest.main()
