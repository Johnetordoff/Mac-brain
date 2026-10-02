import io
import json
import unittest
from unittest.mock import patch

from macbrain import remote


class RemoteControlTests(unittest.TestCase):
    def test_status_is_machine_readable_and_reports_demo_mode(self):
        with patch("macbrain.remote.mission_active", return_value=False), \
             patch("macbrain.remote.CONTAINMENT_MARKER") as marker:
            marker.exists.return_value = False
            result = remote.dispatch_request({"v": 1, "op": "status", "request_id": "r1"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["request_id"], "r1")
        self.assertEqual(result["result"]["mode"], "demo")
        self.assertFalse(result["result"]["containment_armed"])

    def test_demo_mode_allows_read_only_prompt(self):
        with patch("macbrain.remote.mission_active", return_value=False), \
             patch("macbrain.remote.CONTAINMENT_MARKER") as marker, \
             patch("macbrain.remote.agent_ask", return_value="Observed: local evidence") as ask:
            marker.exists.return_value = False
            result = remote.dispatch_request({"v": 1, "op": "ask", "prompt": "what is slow?"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["mode"], "demo")
        ask.assert_called_once_with("what is slow?")

    def test_contained_but_off_cannot_be_started_or_prompted_remotely(self):
        with patch("macbrain.remote.mission_active", return_value=False), \
             patch("macbrain.remote.CONTAINMENT_MARKER") as marker, \
             patch("macbrain.remote.agent_ask") as ask:
            marker.exists.return_value = True
            result = remote.dispatch_request({"v": 1, "op": "ask", "prompt": "start yourself"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "mission_off")
        ask.assert_not_called()

    def test_remote_protocol_has_no_lifecycle_or_destructive_operations(self):
        for op in ("start", "stop", "arm", "approve", "delete", "quarantine", "shell", "exec"):
            result = remote.dispatch_request({"v": 1, "op": op})
            self.assertFalse(result["ok"], op)
            self.assertEqual(result["error"]["code"], "operation_denied")

    def test_prompt_length_is_bounded(self):
        with patch("macbrain.remote.mission_active", return_value=True):
            result = remote.dispatch_request({
                "v": 1,
                "op": "ask",
                "prompt": "x" * (remote.MAX_PROMPT_CHARS + 1),
            })
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "prompt_too_large")

    def test_stdio_is_one_json_request_one_json_response(self):
        src = io.StringIO('{"v":1,"op":"ping","request_id":"abc"}')
        dst = io.StringIO()
        with patch("macbrain.remote.mission_active", return_value=True):
            rc = remote.run_stdio(src, dst)
        self.assertEqual(rc, 0)
        message = json.loads(dst.getvalue())
        self.assertTrue(message["ok"])
        self.assertEqual(message["request_id"], "abc")
        self.assertEqual(message["result"]["service"], "macbrain-remote")

    def test_invalid_json_fails_closed(self):
        dst = io.StringIO()
        rc = remote.run_stdio(io.StringIO("{nope"), dst)
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(dst.getvalue())["error"]["code"], "invalid_json")


if __name__ == "__main__":
    unittest.main()
