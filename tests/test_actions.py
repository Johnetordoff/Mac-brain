import os
import tempfile
import unittest
from pathlib import Path

os.environ["MACBRAIN_HOME"] = tempfile.mkdtemp(prefix="macbrain-actions-")

from macbrain import db
from macbrain.actions import quarantine, _validate_target


class ActionTests(unittest.TestCase):
    def test_system_is_blocked(self):
        with self.assertRaises(PermissionError):
            _validate_target("/System")

    def test_private_etc_is_blocked_after_symlink_resolution(self):
        with self.assertRaises(PermissionError):
            _validate_target("/etc/ssh")
        with self.assertRaises(PermissionError):
            _validate_target("/private/etc/pf.anchors/macbrain")

    def test_macbrain_state_and_ssh_are_blocked(self):
        from macbrain.config import APP_DIR
        with self.assertRaises(PermissionError):
            _validate_target(str(APP_DIR / "macbrain.sqlite3"))
        with self.assertRaises(PermissionError):
            _validate_target(str(Path.home() / ".ssh" / "authorized_keys"))

    def test_quarantine_requires_explicit_cleanup_proposal(self):
        root = Path(tempfile.mkdtemp(prefix="macbrain-file-"))
        target = root / "junk.txt"
        target.write_text("junk")
        pid = db.create_proposal(
            "candidate",
            "ai_cleanup_candidate",
            str(target),
            "concrete evidence that this is a cleanup candidate",
            "reclaim test bytes",
            "test risk",
            "quarantine_then_review",
        )
        self.assertTrue(target.exists())
        dest = quarantine(pid)
        self.assertFalse(target.exists())
        self.assertTrue(dest.exists())

    def test_diagnostic_proposal_cannot_delete_or_quarantine_target(self):
        root = Path(tempfile.mkdtemp(prefix="macbrain-file-"))
        target = root / "important.txt"
        target.write_text("important")
        pid = db.create_proposal(
            "large area worth investigating",
            "large_directory",
            str(target),
            "large only; not evidence it is garbage",
            "possible space savings after inspection",
            "could be important user data",
            "inspect_directory",
        )
        with self.assertRaises(PermissionError):
            quarantine(pid)
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
