"""M17: commit, push and build on command - real output, or git's real error.

The authority rule first: none of this is reachable from the model's tool surface. The sandbox's git
allowlist stays read-only, and these operations run only from a host command behind an explicit grant.

The honesty rule second: an operation either returns what git printed or the error git printed. There
is no invented commit message, no "pushed" without a successful push, and no swallowing of stderr.

Some paths cannot be exercised inside this sandbox: pushing to a local bare remote makes git spawn
sh.exe, which the file sandbox refuses (CreateFileMapping, Win32 error 5). The orchestration is
therefore unit-tested with an injected runner, while the failure path is integration-tested against
real git - which is also where the "show me the error" behaviour matters.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402
import gitops  # noqa: E402


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


class FakeRunner:
    """Records what would run and answers with scripted results."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, args, cwd=None, *, timeout=180):
        self.calls.append([str(item) for item in args])
        if not self.results:
            return dict(ok=True, command=[str(item) for item in args], exit_code=0, output="ok",
                        stdout="ok", stderr="")
        return self.results.pop(0)


class M17GitOperations(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.repo = Path(self.folder.name) / "repo"
        self.repo.mkdir()
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("config", "user.email", "test@example.com", cwd=self.repo)
        git("config", "user.name", "Test", cwd=self.repo)

    def tearDown(self):
        self.folder.cleanup()

    # -- real git -------------------------------------------------------------------------------
    def test_commit_refuses_a_clean_tree_instead_of_inventing_one(self):
        (self.repo / "a.txt").write_text("x\n", encoding="utf-8")
        self.assertTrue(gitops.commit(self.repo, "first")["ok"])
        again = gitops.commit(self.repo, "second")
        self.assertFalse(again["ok"])
        self.assertIn("nothing to commit", again["output"])
        commits = git("rev-list", "--count", "HEAD", cwd=self.repo).stdout.strip()
        self.assertEqual(commits, "1", "a clean tree must not gain a commit")

    def test_commit_uses_a_real_message_and_reports_the_files(self):
        (self.repo / "a.txt").write_text("x\n", encoding="utf-8")
        (self.repo / "b.txt").write_text("y\n", encoding="utf-8")
        result = gitops.commit(self.repo, "")
        self.assertTrue(result["ok"], result["output"])
        self.assertEqual(sorted(result["changed"]), ["a.txt", "b.txt"])
        self.assertRegex(result["message"], r"^checkpoint: 2 file\(s\) changed$")
        subject = git("log", "-1", "--pretty=%s", cwd=self.repo).stdout.strip()
        self.assertEqual(subject, result["message"])

    def test_push_failure_shows_the_error_git_returned(self):
        (self.repo / "a.txt").write_text("x\n", encoding="utf-8")
        gitops.commit(self.repo, "first")
        result = gitops.push(self.repo)
        self.assertFalse(result["ok"], "there is no remote, so the push cannot succeed")
        self.assertTrue(result["output"].strip())
        self.assertIn("fatal:", result["output"].lower(), result["output"][:200])
        self.assertNotIn("pushed", result["output"].lower())

    def test_build_runs_compileall_and_the_package_suite(self):
        result = gitops.build(ROOT)
        self.assertTrue(result["ok"], result["output"][-600:])
        commands = [" ".join(step["command"]) for step in result["steps"]]
        self.assertTrue(any("compileall" in command for command in commands), commands)
        self.assertTrue(any("unittest" in command for command in commands), commands)

    # -- orchestration, with an injected runner --------------------------------------------------
    def test_push_tries_the_authenticated_form_first(self):
        runner = FakeRunner(dict(ok=True, command=[], exit_code=0, output="pushed", stdout="", stderr=""))
        result = gitops.push(self.repo, runner=runner, token_provider=lambda: "secret-token",
                             branch_name="main")
        self.assertTrue(result["ok"])
        first = " ".join(runner.calls[0])
        self.assertIn("extraheader", first)
        self.assertIn("push", first)
        self.assertIn("main", first)

    def test_push_reports_the_last_error_when_both_attempts_fail(self):
        runner = FakeRunner(
            dict(ok=False, command=["git", "push"], exit_code=128, output="first failure: auth",
                 stdout="", stderr=""),
            dict(ok=False, command=["git", "push"], exit_code=128, output="second failure: denied",
                 stdout="", stderr=""))
        result = gitops.push(self.repo, runner=runner, token_provider=lambda: "t", branch_name="main")
        self.assertFalse(result["ok"])
        self.assertIn("second failure: denied", result["output"])
        self.assertEqual(len(result["attempts"]), 2)

    def test_push_without_a_resolvable_branch_fails_cleanly(self):
        result = gitops.push(self.repo, runner=FakeRunner(
            dict(ok=False, command=["git", "rev-parse"], exit_code=128, output="no branch",
                 stdout="", stderr="")))
        self.assertFalse(result["ok"])
        self.assertIn("cannot push", result["output"])

    def test_sync_stops_at_the_commit_when_there_is_nothing_to_commit(self):
        (self.repo / "a.txt").write_text("x\n", encoding="utf-8")
        gitops.commit(self.repo, "first")
        result = gitops.sync(self.repo, "second")
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "commit")
        self.assertIn("nothing to commit", result["output"])

    # -- natural language, through the daemon and the grant --------------------------------
    def test_commit_phrases_are_refused_until_the_grant(self):
        import asyncio
        import session_log
        import user_memory

        async def drive(phrase):
            session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
            user_memory.EVENTS = Path(tempfile.mkdtemp()) / "user.events.jsonl"
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return app.local_answer(phrase), app

        local, app = asyncio.run(drive("commit this"))
        self.assertIsNotNone(local, "commit-this must be answered locally, not by the model")
        kind, body = local
        self.assertEqual(kind, "refused", body)
        self.assertIn("/allow git", body)
        self.assertFalse(app.git_write)

        admitted, why = app.admit_gitop("gitop", "build")
        self.assertTrue(admitted, why)
        self.assertIn("read-only", why)

    # -- the surface the model sees --------------------------------------------------------------
    def test_model_git_tool_stays_read_only(self):
        allowed = chat_app.ALLOWED_PROGRAMS["git"]
        for verb in ("add", "commit", "push"):
            self.assertNotIn(verb, allowed, f"{verb} must not be reachable from the model's tool")
        with self.assertRaises(Exception):
            chat_app.sandbox.run_command("git", ["push"])
        with self.assertRaises(Exception):
            chat_app.sandbox.run_command("git", ["commit", "-m", "x"])


if __name__ == "__main__":
    unittest.main()
