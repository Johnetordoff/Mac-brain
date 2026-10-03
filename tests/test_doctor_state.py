import unittest

from macbrain.lifecycle import worker_expected_running


class DoctorWorkerExpectationTests(unittest.TestCase):
    def test_demo_mode_does_not_require_worker(self):
        self.assertFalse(worker_expected_running(mission_is_active=False))

    def test_active_mission_requires_worker(self):
        self.assertTrue(worker_expected_running(mission_is_active=True))

    def test_installer_can_explicitly_require_worker(self):
        self.assertTrue(
            worker_expected_running(
                mission_is_active=False,
                explicit_expect_running=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
