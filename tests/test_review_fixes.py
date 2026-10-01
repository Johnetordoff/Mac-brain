import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("MACBRAIN_HOME", tempfile.mkdtemp(prefix="macbrain-review-"))

from macbrain import actions, agent, config, db, lifecycle, llm, tools


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class LlamaInvocationTests(unittest.TestCase):
    def test_conversation_mode_is_not_enabled(self):
        args = llm.llama_cli_args(Path("/x/llama-cli"), Path("/x/m.gguf"), "hi", threads=2, context=2048, predict=10, temp="0")
        self.assertNotIn("-cnv", args)
        self.assertNotIn("--conversation", args)
        self.assertNotIn("-no-cnv", args)
        self.assertEqual(args[-2:], ["-p", "hi"])

    def test_generate_never_shares_the_terminal_and_strips_end_marker(self):
        with tempfile.TemporaryDirectory() as td:
            cli = Path(td) / "llama-cli"
            model = Path(td) / "m.gguf"
            cli.write_text("")
            model.write_text("")
            cfg = dict(config.DEFAULT_CONFIG, llama_cli=str(cli), model_path=str(model))
            with mock.patch("macbrain.llm.load_config", return_value=cfg), \
                 mock.patch("macbrain.llm.LLM_LOCK_PATH", Path(td) / "llm.lock"), \
                 mock.patch("macbrain.llm.subprocess.run", return_value=FakeResult(0, "Disk is full. [end of text]\n")) as run:
                out = llm.generate([{"role": "user", "content": "why slow?"}])
        self.assertEqual(out, "Disk is full.")
        self.assertIs(run.call_args.kwargs["stdin"], llm.subprocess.DEVNULL)
        self.assertNotIn("-cnv", run.call_args.args[0])
        self.assertNotIn("-no-cnv", run.call_args.args[0])


class EvidenceBudgetTests(unittest.TestCase):
    def test_prompt_fits_default_context_with_room_to_answer(self):
        cfg = dict(config.DEFAULT_CONFIG)
        question = "x" * 800
        budget = agent.evidence_char_budget(question, cfg)
        # Pessimistic tokenization: 2 chars/token for evidence, 3 for prose.
        tokens = (len(llm.SYSTEM_PROMPT) + len(question)) / 3 + budget / 2 + 64
        self.assertLess(tokens + cfg["llm_predict"], cfg["llm_context"])

    def test_agent_never_sends_more_evidence_than_budget(self):
        prompts = []
        replies = iter(['{"tool":"status","args":{}}', "Answer."])

        def fake_generate(messages):
            prompts.append(messages[0]["content"])
            return next(replies)

        with mock.patch("macbrain.agent.generate", side_effect=fake_generate), \
             mock.patch("macbrain.agent.run_tool", return_value={"blob": "y" * 50000}):
            self.assertEqual(agent.ask("why slow?"), "Answer.")
        budget = agent.evidence_char_budget("why slow?", config.load_config())
        self.assertLessEqual(len(prompts[-1]) - len("why slow?"), budget + 200)


class LifecycleStartTests(unittest.TestCase):
    def test_loaded_but_not_running_is_not_running(self):
        loaded = '{\n\t"Label" = "com.macbrain.performancehunter";\n\t"LastExitStatus" = 0;\n};\n'
        with mock.patch("macbrain.lifecycle.subprocess.run", return_value=FakeResult(0, loaded)):
            self.assertFalse(lifecycle.launch_agent_running())
        with mock.patch("macbrain.lifecycle.subprocess.run", return_value=FakeResult(0, loaded + '\t"PID" = 812;\n')):
            self.assertTrue(lifecycle.launch_agent_running())

    def test_launch_worker_explicitly_starts_the_job(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args[1:])
            return FakeResult(0, '"PID" = 1;' if args[1] == "list" else "")

        with mock.patch("macbrain.lifecycle.subprocess.run", side_effect=fake_run):
            self.assertTrue(lifecycle.launch_worker(wait_seconds=0))
        verbs = [c[0] for c in calls]
        self.assertLess(verbs.index("load"), verbs.index("start"))
        self.assertIn(["start", lifecycle.LABEL], calls)


class CleanupTargetTests(unittest.TestCase):
    def test_deleting_symlink_removes_link_not_destination(self):
        root = Path(tempfile.mkdtemp(prefix="macbrain-link-"))
        real = root / "precious"
        real.mkdir()
        (real / "photo.jpg").write_text("unique")
        link = root / "shortcut"
        link.symlink_to(real)
        pid = db.create_proposal("c", "ai_cleanup_candidate", str(link), "evidence evidence", "benefit", "risk", "quarantine_then_review")
        actions.permanent_delete(pid)
        self.assertFalse(link.is_symlink())
        self.assertTrue((real / "photo.jpg").exists())

    def test_ancestor_of_home_is_refused(self):
        with self.assertRaises(PermissionError):
            actions._validate_target(str(Path.home().resolve().parent))
        with self.assertRaises(PermissionError):
            actions._validate_target("/")


class ReadTextTests(unittest.TestCase):
    def test_reads_only_requested_bytes_from_regular_files(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "big.log"
            f.write_bytes(b"a" * 100000)
            out = tools.tool_read_text({"path": str(f), "max_bytes": 10})
            self.assertEqual(out["bytes_read"], 10)
            with self.assertRaises(ValueError):
                tools.tool_read_text({"path": td})


class PruneTests(unittest.TestCase):
    def test_old_samples_are_pruned(self):
        db.add_sample({"old": True}, ts=time.time() - 30 * 86400)
        db.add_sample({"new": True})
        db.prune(sample_days=14)
        self.assertTrue(all("old" not in s for s in db.recent_samples(1000)))


class BootIdTests(unittest.TestCase):
    def test_unknown_boot_cannot_activate(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(config, "MISSION_ACTIVE_PATH", Path(td) / "mission.active"), \
             mock.patch.object(config, "_boot_id", return_value=config.UNKNOWN_BOOT):
            self.assertFalse(config.set_mission_active(True, user_authorized=True))
            self.assertFalse(config.mission_active())


if __name__ == "__main__":
    unittest.main()
