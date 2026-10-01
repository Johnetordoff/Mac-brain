import tempfile
import unittest
from pathlib import Path
from unittest import mock

import install as installer
from macbrain import llm


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class LlamaRuntimeCompatibilityTests(unittest.TestCase):
    def test_pin_is_pre_refactor_qwen2_build(self):
        self.assertEqual(installer.LLAMA_TAG, "b4400")
        self.assertEqual(installer.LLAMA_COMMIT, "6e1531aca5ed17f078973b4700fcdadbda4a34a5")

    def test_checkout_match_requires_exact_commit(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)
            (src / "Makefile").write_text("legacy makefile")
            with mock.patch.object(installer, "sh", return_value=FakeResult(0, installer.LLAMA_COMMIT + "\n")):
                self.assertTrue(installer.llama_checkout_matches(src))
            with mock.patch.object(installer, "sh", return_value=FakeResult(0, "wrong\n")):
                self.assertFalse(installer.llama_checkout_matches(src))

    def test_old_runtime_does_not_receive_newer_no_cnv_flag(self):
        args = llm.llama_cli_args(
            Path("/x/llama-cli"), Path("/x/model.gguf"), "hi",
            threads=2, context=512, predict=12, temp="0",
        )
        self.assertNotIn("-cnv", args)
        self.assertNotIn("--conversation", args)
        self.assertNotIn("-no-cnv", args)


if __name__ == "__main__":
    unittest.main()
