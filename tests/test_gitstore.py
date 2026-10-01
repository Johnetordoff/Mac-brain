import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macbrain import gitstore


class GitStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "git"
        self.patch = mock.patch.object(gitstore, "GIT_REPOS_DIR", self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_name_validation_blocks_paths(self):
        self.assertEqual(gitstore.validate_repo_name("brain-clone0"), "brain-clone0")
        for bad in ("../brain", "brain/clone", "brain.git", "", "."):
            with self.assertRaises(ValueError):
                gitstore.validate_repo_name(bad)

    def test_create_and_list_bare_repo(self):
        path = gitstore.create_repo("brain-one")
        self.assertTrue((path / "HEAD").exists())
        rows = gitstore.list_repos()
        self.assertEqual([row["name"] for row in rows], ["brain-one"])
        self.assertEqual(rows[0]["commits"], 0)

    def test_import_local_repo(self):
        source = Path(self.tmp.name) / "source"
        source.mkdir()
        subprocess.run(["git", "init", str(source)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
        (source / "hello.txt").write_text("hello\n")
        subprocess.run(["git", "-C", str(source), "add", "hello.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(source), "commit", "-m", "first"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        gitstore.import_local_repo("copy", str(source))
        info = gitstore.repo_summary("copy")
        self.assertEqual(info["commits"], 1)
        self.assertEqual(info["latest"]["subject"], "first")

    def test_import_rejects_network_sources(self):
        for source in ("https://example.com/x.git", "git@example.com:x.git"):
            with self.assertRaises(ValueError):
                gitstore.import_local_repo("copy", source)


if __name__ == "__main__":
    unittest.main()
