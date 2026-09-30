import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macbrain import lifecycle


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class LifecycleTests(unittest.TestCase):
    def test_launch_agent_template_has_no_auto_start_trigger(self):
        text = Path('launchd/com.macbrain.performancehunter.plist.template').read_text()
        self.assertNotIn('<key>RunAtLoad</key>', text)
        self.assertNotIn('<key>KeepAlive</key>', text)
        self.assertNotIn('<key>StartInterval</key>', text)
        self.assertNotIn('<key>StartCalendarInterval</key>', text)

    def test_start_rejects_noninteractive_invocation(self):
        with mock.patch.object(lifecycle.sys.stdin, 'isatty', return_value=False):
            with self.assertRaises(RuntimeError):
                lifecycle.start_mac_brain(require_tty=True)

    def test_start_refuses_without_containment_marker(self):
        with mock.patch.object(lifecycle.sys.stdin, 'isatty', return_value=True), \
             mock.patch('pathlib.Path.exists', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'containment'):
                lifecycle.start_mac_brain(require_tty=True)

    def test_stop_marks_inactive_before_unloading(self):
        calls = []
        with mock.patch('macbrain.lifecycle.set_mission_active', side_effect=lambda active: calls.append(('mission', active))), \
             mock.patch('pathlib.Path.exists', return_value=True), \
             mock.patch('macbrain.lifecycle.subprocess.run', return_value=FakeResult()), \
             mock.patch('macbrain.lifecycle._terminate_local_llama_processes', return_value=[]), \
             mock.patch('macbrain.lifecycle.launch_agent_running', return_value=False):
            lifecycle.stop_mac_brain()
        self.assertEqual(calls[0], ('mission', False))

    def test_plain_activation_call_is_refused(self):
        import tempfile
        from pathlib import Path
        import macbrain.config as cfg
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / "mission.active"
            with mock.patch.object(cfg, "MISSION_ACTIVE_PATH", marker), \
                 mock.patch.object(cfg, "ensure_dirs"), \
                 mock.patch.object(cfg, "_boot_id", return_value="boot-a"):
                self.assertFalse(cfg.set_mission_active(True))
                self.assertFalse(marker.exists())
                self.assertTrue(cfg.set_mission_active(True, user_authorized=True))
                self.assertTrue(marker.exists())


if __name__ == '__main__':
    unittest.main()
