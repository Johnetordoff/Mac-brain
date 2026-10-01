import unittest
from pathlib import Path


class NetworkPolicyStaticTests(unittest.TestCase):
    def setUp(self):
        self.text = Path("scripts/network_lock.sh").read_text()

    def test_only_exact_controller_source_is_passed_to_ssh_rule(self):
        self.assertIn('pass in quick on $IFACE inet proto tcp from $SOURCE to $LOCAL_IP port 22', self.text)
        self.assertNotIn('port 68', self.text)
        self.assertNotIn('port 67', self.text)

    def test_defense_in_depth_disables_internet_routes(self):
        self.assertIn('networksetup -setv6off', self.text)
        self.assertIn('route -n delete default', self.text)
        self.assertIn('network-watchdog.sh', self.text)

    def test_pf_anchor_is_inserted_before_apple_filter_anchor(self):
        self.assertIn('print "anchor \\"macbrain\\""', self.text)
        self.assertIn('!inserted && /^[[:space:]]*anchor "com\\.apple\\/\\*"/', self.text)

    def test_containment_marker_created_by_lock_and_removed_by_unlock(self):
        lock = Path("scripts/network_lock.sh").read_text()
        unlock = Path("scripts/network_unlock.sh").read_text()
        self.assertIn('CONTAINMENT_MARKER="$SUPPORT/containment-active"', lock)
        self.assertIn('echo "armed" > "$CONTAINMENT_MARKER"', lock)
        self.assertIn('CONTAINMENT_MARKER="$SUPPORT/containment-active"', unlock)
        self.assertIn('"$CONTAINMENT_MARKER"', unlock)

    def test_verification_cannot_be_skipped_by_negation(self):
        # bash errexit ignores `! cmd`, so a negated check can never trigger rollback.
        for line in self.text.splitlines():
            self.assertFalse(line.startswith("! "), line)
        self.assertIn("IPv4 default route is still present.", self.text)

    def test_existing_controller_ssh_session_survives_arming(self):
        self.assertIn("port 22 flags any keep state", self.text)
        self.assertIn("trap '' HUP", self.text)

    def test_watchdog_throttles_slow_networksetup_check(self):
        self.assertIn("TICK % 15", self.text)


if __name__ == "__main__":
    unittest.main()
