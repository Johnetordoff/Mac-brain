import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["MACBRAIN_HOME"] = tempfile.mkdtemp(prefix="macbrain-test-")

from macbrain import db
from macbrain.hunter import analyze_snapshot


class HunterTests(unittest.TestCase):
    def test_low_disk_and_swap_create_proposals(self):
        snapshot = {
            "disk": {"total": 100 * 1024**3, "used": 95 * 1024**3, "free": 5 * 1024**3},
            "swap": {"used": 2 * 1024**3, "total": 3 * 1024**3, "free": 1 * 1024**3},
            "processes": [],
        }
        ids = analyze_snapshot(snapshot)
        self.assertGreaterEqual(len(ids), 2)
        kinds = {p["kind"] for p in db.list_proposals("open")}
        self.assertIn("low_disk", kinds)
        self.assertIn("swap_pressure", kinds)

    def test_high_cpu_is_proposal_not_action(self):
        snapshot = {
            "disk": {"total": 100 * 1024**3, "used": 50 * 1024**3, "free": 50 * 1024**3},
            "swap": {"used": 0, "total": 0, "free": 0},
            "processes": [{"pid": 55, "cpu": 99.0, "command": "/Applications/Example.app/Example"}],
        }
        analyze_snapshot(snapshot)
        rows = db.list_proposals("open")
        self.assertTrue(any(r["kind"] == "high_cpu" for r in rows))


if __name__ == "__main__":
    unittest.main()
