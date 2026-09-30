import os
import unittest
from unittest.mock import patch

import install


class InstallLogicTests(unittest.TestCase):
    def test_current_ssh_host_is_exact_controller(self):
        with patch.dict(os.environ, {"SSH_CONNECTION": "192.168.1.44 50000 192.168.1.9 22"}, clear=False):
            self.assertEqual(
                install.authorized_ssh_source({"lan_cidr": "192.168.1.0/24"}),
                "192.168.1.44",
            )

    def test_env_controller_is_used_when_not_installing_over_ssh(self):
        with patch.dict(os.environ, {"SSH_CONNECTION": "", "MACBRAIN_CONTROLLER_IP": "192.168.50.22"}, clear=False):
            self.assertEqual(
                install.authorized_ssh_source({"lan_cidr": "192.168.50.0/24"}),
                "192.168.50.22",
            )

    def test_local_install_prompts_for_one_controller_ip(self):
        with patch.dict(os.environ, {"SSH_CONNECTION": "", "MACBRAIN_CONTROLLER_IP": ""}, clear=False):
            self.assertEqual(
                install.authorized_ssh_source({"lan_cidr": "192.168.50.0/24"}, input_fn=lambda _: "192.168.50.77"),
                "192.168.50.77",
            )

    def test_controller_must_be_same_lan(self):
        with patch.dict(os.environ, {"SSH_CONNECTION": "", "MACBRAIN_CONTROLLER_IP": "10.0.0.8"}, clear=False):
            with self.assertRaises(SystemExit):
                install.authorized_ssh_source({"lan_cidr": "192.168.50.0/24"})

    def test_viability_blocks_too_little_disk(self):
        result = install.viability_assessment(
            memory_bytes=6 * 1024**3, disk_free_bytes=3 * 1024**3,
            battery_source="AC Power", cpu_count=4, load1=0.5,
        )
        self.assertTrue(any("disk" in item for item in result["blockers"]))

    def test_viability_blocks_worn_battery_off_ac_for_unattended_install(self):
        result = install.viability_assessment(
            memory_bytes=6 * 1024**3, disk_free_bytes=20 * 1024**3,
            battery_source="Battery Power", cpu_count=4, load1=0.5,
        )
        self.assertTrue(any("battery" in item.lower() or "ac" in item.lower() for item in result["blockers"]))

    def test_viability_allows_target_class_machine(self):
        result = install.viability_assessment(
            memory_bytes=6 * 1024**3, disk_free_bytes=20 * 1024**3,
            battery_source="AC Power", cpu_count=4, load1=0.5,
        )
        self.assertEqual(result, {"blockers": [], "warnings": []})


if __name__ == "__main__":
    unittest.main()

class MissionBootBindingTests(unittest.TestCase):
    def test_mission_marker_is_bound_to_current_boot(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        import macbrain.config as cfg
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / 'mission.active'
            with mock.patch.object(cfg, 'MISSION_ACTIVE_PATH', marker), \
                 mock.patch.object(cfg, 'ensure_dirs'), \
                 mock.patch.object(cfg, '_boot_id', return_value='boot-a'):
                cfg.set_mission_active(True, user_authorized=True)
                self.assertTrue(cfg.mission_active())
            with mock.patch.object(cfg, 'MISSION_ACTIVE_PATH', marker), \
                 mock.patch.object(cfg, '_boot_id', return_value='boot-b'):
                self.assertFalse(cfg.mission_active())
