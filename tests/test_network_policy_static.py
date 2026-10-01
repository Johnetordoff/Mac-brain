import ast
import unittest
from pathlib import Path


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

    def test_pf_anchor_precedes_apple_filter_anchor(self):
        self.assertIn('output.append(\'anchor "macbrain"\')', self.lock)
        self.assertIn("apple_anchor", self.lock)

    def test_containment_marker_created_and_removed(self):
        self.assertIn('SUPPORT / "containment-active"', self.lock)
        self.assertIn('CONTAINMENT_MARKER.write_text("armed', self.lock)
        self.assertIn('SUPPORT / "containment-active"', self.unlock)
        self.assertIn("CONTAINMENT_MARKER", self.unlock)

    def test_installer_never_invokes_a_shell_interpreter(self):
        self.assertNotIn("/bin/bash", self.install)
        self.assertNotIn("network_lock.sh", self.install)
        self.assertNotIn("network_unlock.sh", self.install)
        self.assertIn("network_lock.py", self.install)
        self.assertIn("macbrain-wrapper.py", self.install)


if __name__ == "__main__":
    unittest.main()
