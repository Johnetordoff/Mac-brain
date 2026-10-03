import unittest
from unittest import mock

from macbrain.diagnostics import build_diagnostic_packet


class DiagnosticTests(unittest.TestCase):
    def _snapshot(self):
        return {
            "load": {"1m": 4.0, "5m": 3.5, "15m": 3.0, "cpus": 4},
            "memory_total": 6 * 1024**3,
            "disk": {
                "total": 233 * 1024**3,
                "used": 170 * 1024**3,
                "free": 63 * 1024**3,
            },
            "swap": {
                "total": 4 * 1024**3,
                "used": 2 * 1024**3,
                "free": 2 * 1024**3,
            },
            "battery": {"source": "AC Power", "percent": 100, "status": "charged"},
            "thermal": "",
            "processes": [
                {
                    "pid": 681,
                    "ppid": 1,
                    "cpu": 94.0,
                    "mem_pct": 1.0,
                    "rss_kb": 65536,
                    "etime": "01:00:00",
                    "command": "/System/Library/CoreServices/ReportCrash",
                }
            ],
        }

    def test_reportcrash_becomes_engineering_request(self):
        snapshot = self._snapshot()
        history = [snapshot, snapshot, snapshot]
        process_rows = [{
            "command": "/System/Library/CoreServices/ReportCrash",
            "first_seen_ts": 1.0,
            "last_seen_ts": 3.0,
            "samples": 3,
            "cpu_sum": 280.0,
            "cpu_max": 96.0,
            "rss_kb_sum": 180000,
            "rss_kb_max": 70000,
            "last_pid": 681,
            "necessity_state": "unknown",
            "necessity_evidence": "",
            "cpu_avg": 280.0 / 3.0,
            "rss_kb_avg": 60000.0,
        }]
        fs = {
            "files_seen": 100,
            "file_bytes_indexed": 10 * 1024**3,
            "frontier_directories": 40,
            "necessity_counts": {"unknown": 100},
            "largest_files": [],
        }
        with mock.patch("macbrain.diagnostics.collect_snapshot", return_value=snapshot), \
             mock.patch("macbrain.diagnostics.db.add_sample"), \
             mock.patch("macbrain.diagnostics.db.record_process_snapshot"), \
             mock.patch("macbrain.diagnostics.db.recent_samples", return_value=history), \
             mock.patch("macbrain.diagnostics.db.process_inventory", return_value=process_rows), \
             mock.patch("macbrain.diagnostics.db.filesystem_crawl_stats", return_value=fs), \
             mock.patch("macbrain.diagnostics.db.add_observation"):
            packet = build_diagnostic_packet(sample_limit=60)

        kinds = [item["kind"] for item in packet["bottlenecks"]]
        self.assertIn("crash_loop_signal", kinds)
        requests = packet["engineering_requests"]
        self.assertTrue(any(item["subject"].endswith("ReportCrash") for item in requests))
        self.assertTrue(packet["safety"]["diagnostic_only"])

    def test_diagnostics_do_not_call_destructive_actions(self):
        snapshot = self._snapshot()
        with mock.patch("macbrain.diagnostics.collect_snapshot", return_value=snapshot), \
             mock.patch("macbrain.diagnostics.db.add_sample"), \
             mock.patch("macbrain.diagnostics.db.record_process_snapshot"), \
             mock.patch("macbrain.diagnostics.db.recent_samples", return_value=[snapshot]), \
             mock.patch("macbrain.diagnostics.db.process_inventory", return_value=[]), \
             mock.patch("macbrain.diagnostics.db.filesystem_crawl_stats", return_value={
                 "files_seen": 0,
                 "file_bytes_indexed": 0,
                 "frontier_directories": 0,
                 "necessity_counts": {},
                 "largest_files": [],
             }), \
             mock.patch("macbrain.diagnostics.db.add_observation"):
            packet = build_diagnostic_packet()
        self.assertFalse(packet["safety"]["automatic_process_termination"])
        self.assertFalse(packet["safety"]["automatic_file_deletion"])
        self.assertFalse(packet["safety"]["automatic_service_disable"])


if __name__ == "__main__":
    unittest.main()
