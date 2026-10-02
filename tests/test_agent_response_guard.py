import unittest
from unittest.mock import patch

from macbrain import agent


class AgentResponseGuardTests(unittest.TestCase):
    def test_exact_reply_bypasses_local_model(self):
        with patch("macbrain.agent.generate") as generate:
            answer = agent.ask("Reply with exactly: MAC BRAIN READY")
        self.assertEqual(answer, "MAC BRAIN READY")
        generate.assert_not_called()

    def test_exact_reply_supports_matching_quotes(self):
        with patch("macbrain.agent.generate") as generate:
            answer = agent.ask('Reply exactly: "READY"')
        self.assertEqual(answer, "READY")
        generate.assert_not_called()

    def test_tool_catalog_echo_is_detected(self):
        echoed = (
            '{"tool":"status","args":{}}\n'
            '{"tool":"processes","args":{"limit":20}}\n'
            '{"tool":"storage","args":{}}'
        )
        self.assertTrue(agent._looks_like_tool_catalog_echo(echoed))

    def test_single_tool_call_is_not_catalog_echo(self):
        self.assertFalse(
            agent._looks_like_tool_catalog_echo('{"tool":"status","args":{}}')
        )

    def test_catalog_echo_is_retried_and_never_returned_verbatim(self):
        echoed = (
            '{"tool":"status","args":{}}\n'
            '{"tool":"processes","args":{"limit":20}}'
        )
        with patch("macbrain.agent.load_config", return_value={"llm_context": 2048, "llm_predict": 320}), \
             patch("macbrain.agent.generate", side_effect=[echoed, "Direct answer"]):
            answer = agent.ask("What is going on?")
        self.assertEqual(answer, "Direct answer")

    def test_repeated_catalog_echo_fails_closed(self):
        echoed = (
            '{"tool":"status","args":{}}\n'
            '{"tool":"processes","args":{"limit":20}}'
        )
        with patch("macbrain.agent.load_config", return_value={"llm_context": 2048, "llm_predict": 320}), \
             patch("macbrain.agent.generate", side_effect=[echoed, echoed]):
            answer = agent.ask("What is going on?")
        self.assertIn("echoed its tool catalog", answer)
        self.assertNotEqual(answer, echoed)


if __name__ == "__main__":
    unittest.main()
