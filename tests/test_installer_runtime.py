import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install as installer


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class LlamaRuntimePinTests(unittest.TestCase):
    def test_pin_is_pre_refactor_qwen2_build(self):
        self.assertEqual(installer.LLAMA_TAG, "b4400")
        self.assertEqual(installer.LLAMA_COMMIT, "6e1531aca5ed17f078973b4700fcdadbda4a34a5")

    def test_checkout_match_requires_exact_commit(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)
            (src / "Makefile").write_text("legacy makefile")
            with mock.patch.object(installer, "sh", return_value=FakeResult(0, installer.LLAMA_COMMIT + "\n")):
                self.assertTrue(installer.llama_checkout_matches(src))
            with mock.patch.object(installer, "sh", return_value=FakeResult(0, "c64d2becb13f2a7c0145b516a05f028d949a046b\n")):
                self.assertFalse(installer.llama_checkout_matches(src))

    def test_missing_makefile_never_matches(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(installer, "sh") as sh:
                self.assertFalse(installer.llama_checkout_matches(Path(td)))
                sh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
