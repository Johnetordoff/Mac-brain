import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macbrain import db


class ProcessInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="macbrain-process-db-")
        self.db_path = Path(self.tempdir.name) / "macbrain.sqlite3"
        self.patch = mock.patch.object(db, "DB_PATH", self.db_path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tempdir.cleanup()

    def test_same_command_instances_are_aggregated_per_sample(self):
        db.record_process_snapshot([
            {"command": "/Applications/App", "pid": 10, "cpu": 20.0, "rss_kb": 100},
            {"command": "/Applications/App", "pid": 11, "cpu": 30.0, "rss_kb": 200},
        ], ts=100.0)
        rows = db.process_inventory()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["samples"], 1)
        self.assertEqual(rows[0]["cpu_avg"], 50.0)
        self.assertEqual(rows[0]["cpu_max"], 50.0)
        self.assertEqual(rows[0]["rss_kb_max"], 300)

    def test_process_classification_survives_more_samples(self):
        command = "/Applications/OptionalHelper"
        db.record_process_snapshot([
            {"command": command, "pid": 20, "cpu": 5.0, "rss_kb": 1000},
        ], ts=100.0)
        db.classify_process(
            command,
            "probably_unnecessary",
            "Human says this helper is not needed for the appliance role.",
        )
        db.record_process_snapshot([
            {"command": command, "pid": 21, "cpu": 10.0, "rss_kb": 1200},
        ], ts=200.0)
        row = db.process_inventory()[0]
        self.assertEqual(row["samples"], 2)
        self.assertEqual(row["necessity_state"], "probably_unnecessary")
        self.assertIn("appliance role", row["necessity_evidence"])


if __name__ == "__main__":
    unittest.main()
