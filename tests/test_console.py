import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

os.environ["MACBRAIN_HOME"] = tempfile.mkdtemp(prefix="macbrain-console-")

from macbrain import db
from macbrain.console import is_takeover_phrase, run_prearm_console
from macbrain.config import mission_active, set_mission_active


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        set_mission_active(False)

    def test_natural_language_does_not_count_as_takeover_codeword(self):
        self.assertFalse(is_takeover_phrase("Yeah, I know you are. Go for it."))

    def test_takeover_requires_explicit_takeover_language(self):
        self.assertTrue(is_takeover_phrase("TAKE OVER MAC BRAIN"))
        self.assertFalse(is_takeover_phrase("can you speed this up?"))
        self.assertFalse(is_takeover_phrase("yeah go for it"))

    def test_mission_state_persists_in_local_state(self):
        self.assertFalse(mission_active())
        set_mission_active(True, user_authorized=True)
        self.assertTrue(mission_active())
        set_mission_active(False)
        self.assertFalse(mission_active())

    def test_demo_can_reason_then_takeover_without_starting_mission(self):
        output = io.StringIO()
        with patch("builtins.input", side_effect=["can you speed this up?", "TAKE OVER MAC BRAIN"]), \
             patch("macbrain.console.agent_ask", return_value="Observed: test evidence") as ask, \
             redirect_stdout(output):
            rc = run_prearm_console()
        self.assertEqual(rc, 0)
        self.assertTrue(ask.called)
        self.assertFalse(mission_active())
        self.assertIn("MAC BRAIN DEMONSTRATION STAGE", output.getvalue())

    def test_reports_are_ordered_and_incremental(self):
        start = db.latest_report_id()
        first = db.add_report("heartbeat", "still hunting")
        second = db.add_report("ai", "hypothesis update")
        rows = db.reports_since(start)
        self.assertEqual([r["id"] for r in rows], [first, second])
        self.assertEqual(db.reports_since(first)[0]["id"], second)


if __name__ == "__main__":
    unittest.main()
