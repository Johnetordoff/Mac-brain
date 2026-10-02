import json
import subprocess
import unittest
from unittest.mock import patch

from controller.macbrain_remote import build_request, call_macbrain


class ControllerClientTests(unittest.TestCase):
    def test_build_ask_request(self):
        req = build_request("ask", prompt=" hello ", request_id="r1")
        self.assertEqual(req, {"v": 1, "op": "ask", "request_id": "r1", "prompt": "hello"})

    def test_ask_requires_prompt(self):
        with self.assertRaises(ValueError):
            build_request("ask", prompt="   ")

    def test_client_waits_for_single_json_reply(self):
        completed = subprocess.CompletedProcess(
            args=["ssh"],
            returncode=0,
            stdout='{"v":1,"request_id":"r1","ok":true,"result":{"answer":"yes"}}\n',
            stderr="",
        )
        with patch("controller.macbrain_remote.subprocess.run", return_value=completed) as run:
            response = call_macbrain(
                host="192.0.2.10",
                user="john",
                identity_file="~/.ssh/macbrain_remote",
                request={"v": 1, "op": "ask", "request_id": "r1", "prompt": "test"},
                timeout_seconds=77,
            )
        self.assertTrue(response["ok"])
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 77)
        self.assertTrue(kwargs["capture_output"])
        self.assertIn('"request_id":"r1"', kwargs["input"])

    def test_timeout_is_unknown_completion_state(self):
        with patch(
            "controller.macbrain_remote.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["ssh"], timeout=5),
        ):
            with self.assertRaisesRegex(RuntimeError, "do not assume the request completed"):
                call_macbrain(
                    host="192.0.2.10",
                    user="john",
                    identity_file="~/.ssh/macbrain_remote",
                    request={"v": 1, "op": "ping", "request_id": "r1"},
                    timeout_seconds=5,
                )

    def test_remote_protocol_error_is_still_parsed(self):
        completed = subprocess.CompletedProcess(
            args=["ssh"],
            returncode=2,
            stdout='{"v":1,"ok":false,"error":{"code":"mission_off","message":"off"}}\n',
            stderr="",
        )
        with patch("controller.macbrain_remote.subprocess.run", return_value=completed):
            response = call_macbrain(
                host="192.0.2.10",
                user="john",
                identity_file="~/.ssh/macbrain_remote",
                request={"v": 1, "op": "ask", "request_id": "r1", "prompt": "test"},
            )
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "mission_off")


if __name__ == "__main__":
    unittest.main()
