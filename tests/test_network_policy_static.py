import ast
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import network_lock


class NetworkPolicyStaticTests(unittest.TestCase):
    def setUp(self):
        self.lock = Path("scripts/network_lock.py").read_text()
        self.unlock = Path("scripts/network_unlock.py").read_text()
        self.watchdog = Path("scripts/network_watchdog.py").read_text()
        self.install = Path("install.py").read_text()

    def test_containment_programs_are_python(self):
        for path in (
            Path("scripts/network_lock.py"),
            Path("scripts/network_unlock.py"),
            Path("scripts/network_watchdog.py"),
            Path("scripts/uninstall.py"),
        ):
            ast.parse(path.read_text(), filename=str(path))
            self.assertIn("python", path.read_text().splitlines()[0].lower())
        self.assertEqual(list(Path("scripts").glob("*.sh")), [])

    def test_only_exact_controller_source_is_passed_to_ssh_rule(self):
        self.assertIn("pass in quick on {args.interface} inet proto tcp from {args.source}", self.lock)
        self.assertIn("port 22 flags any keep state", self.lock)
        self.assertNotIn("port 68", self.lock)
        self.assertNotIn("port 67", self.lock)

    def test_defense_in_depth_disables_internet_routes(self):
        self.assertIn('"-setv6off"', self.lock)
        self.assertIn('"delete", "default"', self.lock)
        self.assertIn("network_watchdog.py", self.lock)
        self.assertIn('"delete", "default"', self.watchdog)

    def test_apple_anchor_recognition_and_ordering_are_unambiguous(self):
        self.assertTrue(network_lock._is_apple_filter_anchor('anchor "com.apple/*"'))
        self.assertTrue(network_lock._is_apple_filter_anchor('  anchor "com.apple/*"  '))
        self.assertFalse(network_lock._is_apple_filter_anchor('anchor "macbrain"'))

        with tempfile.TemporaryDirectory() as td:
            pf = Path(td) / "pf.conf"
            out = Path(td) / "pf.new"
            pf.write_text('set skip on lo0\nanchor "com.apple/*"\npass all\n')
            with mock.patch.object(network_lock, "PF_CONF", pf), \
                 mock.patch.object(network_lock, "PF_NEW", out), \
                 mock.patch.object(network_lock, "root_private"):
                network_lock.build_pf_config()
            lines = out.read_text().splitlines()
        self.assertLess(lines.index('anchor "macbrain"'), lines.index('anchor "com.apple/*"'))
        self.assertEqual(lines.count('anchor "macbrain"'), 1)

    def test_containment_marker_created_and_removed(self):
        self.assertIn('SUPPORT / "containment-active"', self.lock)
        self.assertIn('CONTAINMENT_MARKER.write_text("armed', self.lock)
        self.assertIn('SUPPORT / "containment-active"', self.unlock)
        self.assertIn("CONTAINMENT_MARKER", self.unlock)

    def test_remote_control_opens_no_network_client_path(self):
        remote = Path("macbrain/remote.py").read_text()
        for forbidden in (
            "import socket",
            "from socket",
            "urllib.request",
            "http.client",
            "requests",
            "websocket",
            "subprocess",
            "os.system",
        ):
            self.assertNotIn(forbidden, remote)
        self.assertIn('frozenset({"ping", "status", "ask", "proposals"})', remote)

    def test_installer_never_invokes_a_shell_interpreter(self):
        self.assertNotIn("/bin/bash", self.install)
        self.assertNotIn("network_lock.sh", self.install)
        self.assertNotIn("network_unlock.sh", self.install)
        self.assertIn("network_lock.py", self.install)
        self.assertIn("macbrain-wrapper.py", self.install)


if __name__ == "__main__":
    unittest.main()
