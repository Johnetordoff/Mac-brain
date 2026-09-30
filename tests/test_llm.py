import unittest
from macbrain.llm import maybe_tool_call


class LLMTests(unittest.TestCase):
    def test_tool_json(self):
        self.assertEqual(maybe_tool_call('{"tool":"status","args":{}}')["tool"], "status")

    def test_plain_answer(self):
        self.assertIsNone(maybe_tool_call("The disk is nearly full."))


if __name__ == "__main__":
    unittest.main()
