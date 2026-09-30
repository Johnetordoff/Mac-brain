import unittest
from unittest.mock import patch

from macbrain.security import _is_review_location, security_baseline


class SecurityAuditTests(unittest.TestCase):
    def test_downloads_and_tmp_are_review_locations(self):
        import pathlib
        self.assertTrue(_is_review_location(str(pathlib.Path.home() / "Downloads" / "mystery")))
        self.assertTrue(_is_review_location("/private/tmp/mystery"))
        self.assertFalse(_is_review_location("/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder"))

    @patch("macbrain.security._apple_security_components", return_value={"xprotect": {"present": True}})
    @patch("macbrain.security._listeners", return_value={"listeners": [], "review_items": [{"kind": "listener", "reasons": ["test"]}]})
    @patch("macbrain.security._persistence_inventory", return_value={"items": [], "review_items": []})
    @patch("macbrain.security._process_inventory", return_value={"process_count": 10, "third_party_process_count": 2, "signature_paths_checked": 2, "processes": [], "signatures": {}, "review_items": []})
    def test_baseline_calls_findings_review_not_malware(self, _p, _persist, _listeners, _apple):
        result = security_baseline()
        self.assertEqual(result["process_count"], 10)
        self.assertEqual(result["review_item_count"], 1)
        self.assertIn("does not claim malware", result["interpretation"])


if __name__ == "__main__":
    unittest.main()
