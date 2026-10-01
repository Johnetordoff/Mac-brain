import os
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

    def test_create_repo_installs_low_cost_storage_guards(self):
        path = gitstore.create_repo("brain-one")
        self.assertTrue((path / "HEAD").exists())
        self.assertEqual(gitstore.list_repos(), ["brain-one"])

        def get_config(key):
            return subprocess.run(
                ["git", "--git-dir", str(path), "config", "--get", key],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()

        self.assertEqual(get_config("gc.auto"), "0")
        self.assertEqual(get_config("receive.autogc"), "false")
        self.assertEqual(get_config("receive.maxInputSize"), str(gitstore.MAX_RECEIVE_BYTES))

        hook = path / "hooks" / "pre-receive"
        self.assertTrue(hook.exists())
        self.assertTrue(os.access(str(hook), os.X_OK))
        text = hook.read_text()
        self.assertIn("low disk space", text)
        self.assertIn("MIN_RESERVE_KB=1048576", text)

    def test_push_in_from_local_source_and_explicit_info(self):
        target = gitstore.create_repo("brain-one")
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
        subprocess.run(
            ["git", "-C", str(source), "push", str(target), "HEAD:refs/heads/main"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["git", "--git-dir", str(target), "symbolic-ref", "HEAD", "refs/heads/main"],
            check=True,
        )

        info = gitstore.repo_summary("brain-one")
        self.assertEqual(info["branches"], 1)
        self.assertEqual(info["latest"]["subject"], "first")
        self.assertFalse(info["automatic_gc"])
        self.assertEqual(info["max_receive_bytes"], gitstore.MAX_RECEIVE_BYTES)

    def test_capacity_is_filesystem_level_and_reserves_at_least_one_gib(self):
        gib = 1024 * 1024 * 1024
        usage = type("Usage", (), {
            "total": 8 * gib,
            "used": 6 * gib,
            "free": 2 * gib,
        })()
        with mock.patch.object(gitstore.shutil, "disk_usage", return_value=usage):
            capacity = gitstore.storage_capacity()
        self.assertEqual(capacity["reserve"], gitstore.MIN_FREE_RESERVE_BYTES)
        self.assertTrue(capacity["write_ok"])

    def test_creation_fails_closed_when_storage_reserve_is_reached(self):
        with mock.patch.object(
            gitstore,
            "storage_capacity",
            return_value={
                "total": 10,
                "used": 9,
                "free": 1,
                "reserve": 1,
                "write_ok": False,
                "max_receive_bytes": gitstore.MAX_RECEIVE_BYTES,
            },
        ):
            with self.assertRaises(RuntimeError):
                gitstore.create_repo("no-space")
        self.assertFalse((self.root / "no-space.git").exists())

    def test_git_vault_has_no_network_import_operation(self):
        self.assertFalse(hasattr(gitstore, "import_local_repo"))


if __name__ == "__main__":
    unittest.main()
