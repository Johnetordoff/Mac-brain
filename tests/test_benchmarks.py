import unittest

from macbrain.benchmarks import compare_runs


class BenchmarkComparisonTests(unittest.TestCase):
    def test_first_run_is_baseline(self):
        result = compare_runs({"metrics": {}}, None)
        self.assertEqual(result["verdict"], "baseline")

    def test_clear_speed_improvement_is_improved(self):
        previous = {
            "metrics": {
                "cpu_seconds_median": 10.0,
                "disk_write_mib_per_second": 50.0,
                "disk_read_mib_per_second": 100.0,
                "inference_seconds": 20.0,
                "disk_free_bytes": 100_000_000_000,
                "swap_used_bytes": 2_000_000_000,
            }
        }
        current = {
            "metrics": {
                "cpu_seconds_median": 8.0,
                "disk_write_mib_per_second": 65.0,
                "disk_read_mib_per_second": 125.0,
                "inference_seconds": 16.0,
                "disk_free_bytes": 110_000_000_000,
                "swap_used_bytes": 1_500_000_000,
            }
        }
        result = compare_runs(current, previous)
        self.assertEqual(result["verdict"], "improved")
        self.assertGreater(result["improved_metrics"], 0)
        self.assertEqual(result["regressed_metrics"], 0)

    def test_conflicting_changes_are_mixed_not_fake_success(self):
        previous = {
            "metrics": {
                "cpu_seconds_median": 10.0,
                "disk_write_mib_per_second": 50.0,
                "disk_read_mib_per_second": 100.0,
                "inference_seconds": 20.0,
                "disk_free_bytes": 100_000_000_000,
                "swap_used_bytes": 1_000_000_000,
            }
        }
        current = {
            "metrics": {
                "cpu_seconds_median": 8.0,
                "disk_write_mib_per_second": 35.0,
                "disk_read_mib_per_second": 100.0,
                "inference_seconds": 20.0,
                "disk_free_bytes": 100_000_000_000,
                "swap_used_bytes": 1_000_000_000,
            }
        }
        result = compare_runs(current, previous)
        self.assertEqual(result["verdict"], "mixed")


if __name__ == "__main__":
    unittest.main()
