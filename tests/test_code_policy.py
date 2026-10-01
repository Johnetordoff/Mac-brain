import unittest

from macbrain.code_policy import enforce_response_code_policy, validate_generated_file, validate_python_source


class CodePolicyTests(unittest.TestCase):
    def test_standard_library_python_is_allowed(self):
        validate_python_source("import json\nfrom pathlib import Path\nprint(json.dumps({'x': str(Path('.'))}))\n")

    def test_third_party_python_import_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_python_source("import requests\n")

    def test_shell_program_output_is_rejected(self):
        with self.assertRaises(ValueError):
            enforce_response_code_policy("```bash\necho nope\n```")

    def test_python_program_output_is_allowed(self):
        text = "```python\nimport json\nprint(json.dumps({'ok': True}))\n```"
        self.assertEqual(enforce_response_code_policy(text), text)

    def test_javascript_requires_browser_path_or_context(self):
        with self.assertRaises(ValueError):
            validate_generated_file("scripts/tool.js", "console.log('no')")
        validate_generated_file("web/tool.js", "console.log('ok')")
        with self.assertRaises(ValueError):
            enforce_response_code_policy("```javascript\nconsole.log('no')\n```")
        text = "```javascript\nconsole.log('ok')\n```"
        self.assertEqual(enforce_response_code_policy(text, browser_context=True), text)

    def test_declarative_files_are_allowed(self):
        validate_generated_file("config/settings.json", '{"x": 1}\n')
        validate_generated_file("config/settings.toml", "x = 1\n")


if __name__ == "__main__":
    unittest.main()
