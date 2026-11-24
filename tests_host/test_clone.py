"""M18: cloning is a write, so it is validated, contained, and granted - and never guessed.

Three surfaces reach `gitops.clone`: the host `/clone` command, the `GITOP clone` intent (which asks
for a url, because an AIML kernel splits a url on sentence punctuation), and the model's
`clone_repo` tool. All three share one validator and one grant.

What is refused before any network call: a non-https scheme, a flag smuggled in as a url, shell
metacharacters, and a destination that escapes the workspace or is not empty.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402
import gitops  # noqa: E402


class FakeRunner:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __call__(self, args, cwd=None, *, timeout=180):
        self.calls.append([str(item) for item in args])
        return self.result or dict(ok=True, command=[str(item) for item in args], exit_code=0,
                                   output="Cloning into 'y'...\ndone.", stdout="", stderr="")


class M18Clone(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        chat_app.sandbox.allow_write = False

    def tearDown(self):
        chat_app.sandbox.allow_write = False
        self.folder.cleanup()

    # -- url and destination validation ---------------------------------------------------------
    def test_only_https_remotes_are_accepted(self):
        self.assertTrue(gitops.validate_remote("https://github.com/someone/repo.git")["ok"])
        for url in ("ssh://git@host/x.git", "git@github.com:x/y.git", "file:///etc/passwd",
                    "ext::sh -c touch% /tmp/pwned", "http://example.com/x.git"):
            self.assertFalse(gitops.validate_remote(url)["ok"], url)

    def test_flags_and_shell_metacharacters_are_refused(self):
        for url in ("-u", "--upload-pack=evil", "https://x/y.git; rm -rf /",
                    "https://x/y.git && curl evil", "https://x/$(whoami).git"):
            verdict = gitops.validate_remote(url)
            self.assertFalse(verdict["ok"], url)
            self.assertTrue(verdict["problems"])

    def test_destination_stays_inside_the_workspace(self):
        ok = gitops.validate_destination(self.root, "https://x/y.git", "clones/repo")
        self.assertTrue(ok["ok"])
        self.assertTrue(ok["path"].startswith(str(self.root)))
        for destination in ("../escape", "/abs/path", "C:\\Windows\\Temp\\x"):
            self.assertFalse(gitops.validate_destination(self.root, "https://x/y.git", destination)["ok"])

    def test_a_non_empty_destination_is_refused(self):
        busy = self.root / "y"
        busy.mkdir()
        (busy / "file.txt").write_text("x", encoding="utf-8")
        verdict = gitops.validate_destination(self.root, "https://x/y.git", "y")
        self.assertFalse(verdict["ok"])
        self.assertIn("not empty", " ".join(verdict["problems"]))

    # -- the clone call itself ------------------------------------------------------------------
    def test_clone_derives_the_directory_from_the_url(self):
        runner = FakeRunner()
        result = gitops.clone("https://github.com/someone/repo.git", root=self.root, runner=runner)
        self.assertTrue(result["ok"], result["output"])
        self.assertEqual(Path(result["path"]).name, "repo")
        argv = runner.calls[0]
        self.assertIn("--depth", argv)
        self.assertEqual(argv[-2], "https://github.com/someone/repo.git")
        self.assertEqual(argv[-1], result["path"])

    def test_clone_reports_gits_error_when_it_fails(self):
        failure = dict(ok=False, command=["git", "clone"], exit_code=128,
                       output="fatal: repository 'https://x/y.git' not found", stdout="", stderr="")
        result = gitops.clone("https://x/y.git", root=self.root, runner=FakeRunner(failure))
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["output"])
        self.assertEqual(result["exit_code"], 128)

    def test_a_refused_url_never_reaches_the_runner(self):
        runner = FakeRunner()
        result = gitops.clone("ssh://git@h/x.git", root=self.root, runner=runner)
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("refused"))
        self.assertEqual(runner.calls, [], "validation must happen before any subprocess")

    # -- the three surfaces ---------------------------------------------------------------------
    def test_the_model_tool_needs_the_write_grant(self):
        chat_app.sandbox.allow_write = False
        out = chat_app.execute_tool("clone_repo", {"url": "https://github.com/x/y.git"})
        self.assertIn("refused", out)
        self.assertIn("/allow", out)
        chat_app.sandbox.allow_write = True
        out = chat_app.execute_tool("clone_repo", {"url": "ssh://git@h/x.git"})
        self.assertIn("refused", out)
        self.assertIn("https", out)

    def test_the_gitop_intent_needs_the_write_grant(self):
        app = chat_app.ChatApp()
        chat_app.sandbox.allow_write = False
        admitted, why = app.admit_gitop("gitop", "clone https://github.com/x/y.git")
        self.assertFalse(admitted)
        self.assertIn("/allow", why)
        chat_app.sandbox.allow_write = True
        admitted, why = app.admit_gitop("gitop", "clone https://github.com/x/y.git")
        self.assertTrue(admitted, why)

    def test_the_intent_without_a_url_asks_for_one(self):
        app = chat_app.ChatApp()
        chat_app.sandbox.allow_write = True
        out = app.execute_gitop("clone")
        self.assertIn("/clone", out)
        self.assertIn("Nothing was changed", out)

    def test_plain_git_clone_stays_unreachable_from_the_sandbox(self):
        self.assertNotIn("clone", chat_app.ALLOWED_PROGRAMS["git"])
        with self.assertRaises(Exception):
            chat_app.sandbox.run_command("git", ["clone", "https://github.com/x/y.git"])


if __name__ == "__main__":
    unittest.main()
