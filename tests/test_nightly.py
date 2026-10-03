import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macbrain import nightly


class NightlyTests(unittest.TestCase):
    def test_nightly_writes_durable_handoff(self):
        root = Path(tempfile.mkdtemp(prefix="macbrain-nightly-"))
        benchmark = {
            "repo_commit": "abc123",
            "metrics": {
                "disk_free_bytes": 10 * 1024**3,
                "swap_used_bytes": 1024**3,
                "load_per_cpu": 0.25,
            },
            "comparison": {"verdict": "baseline", "metrics": []},
        }
        diagnostic = {
            "filesystem_inventory": {
                "files_seen": 12,
                "file_bytes_indexed": 2 * 1024**3,
                "frontier_directories": 3,
            },
            "bottlenecks": [],
            "engineering_requests": [],
        }
        crawl = {"complete": True, "entries_seen": 8, "frontier_directories": 0}

        with mock.patch.object(nightly, "HANDOFF_DIR", root), \
             mock.patch("macbrain.nightly.load_config", return_value={"nightly_crawl_minutes": 5, "nightly_include_inference_benchmark": True}), \
             mock.patch("macbrain.nightly.run_benchmarks", return_value=benchmark), \
             mock.patch("macbrain.nightly.crawl_step", return_value=crawl), \
             mock.patch("macbrain.nightly.build_diagnostic_packet", return_value=diagnostic), \
             mock.patch("macbrain.nightly.db.set_runtime_state"), \
             mock.patch("macbrain.nightly.db.add_report"):
            packet = nightly.run_nightly(include_model_review=False)
            latest = nightly.latest_nightly()

        self.assertEqual(packet["benchmark"]["comparison"]["verdict"], "baseline")
        self.assertTrue((root / "latest.json").exists())
        self.assertTrue((root / "latest.txt").exists())
        self.assertIn("BENCHMARKS", (root / "latest.txt").read_text())
        self.assertIsNotNone(latest)


if __name__ == "__main__":
    unittest.main()
