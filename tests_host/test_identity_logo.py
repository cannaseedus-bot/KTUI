"""M14: the daemon answers as itself, and its mark is a title rather than a poster.

The identity answer must come from the *host*, not from a bank: the name, the phases, the model list
and the mark are all read from the running configuration, so they cannot drift from what is loaded.
And it must not be ALICE: the vendored corpus is data, not identity.

The logo assertions are deliberately about the rendered box, because that is what "too big" meant -
the PNG's pixel size alone would not have shrunk the header.
"""
import inspect
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aiml  # noqa: E402
import daemon  # noqa: E402

PHRASES = ("who are you", "what is your name", "are you alice", "what models can you talk to")


class M14IdentityAndMark(unittest.TestCase):
    def test_bank_routes_identity_questions_to_the_directive(self):
        kernel = aiml.Kernel()
        kernel.learn(str(ROOT / "identity.aiml"))
        for phrase in PHRASES:
            self.assertEqual(kernel.respond(phrase), "IDENTITY", phrase)

    def test_daemon_admits_identity_as_local_text(self):
        kernel = aiml.Kernel()
        kernel.learn(str(ROOT / "identity.aiml"))
        engine = daemon.Daemon(kernel=lambda text: kernel.respond(text), banks=[],
                               admit=lambda verb, arg: (False, "no tools here"),
                               admit_plan=lambda name: (False, "no plans here"))
        turn = engine.run("who are you")
        self.assertEqual(turn.kind, "identity")
        phases = [name for name, _ in turn.phases]
        self.assertEqual(phases, ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])

    def test_identity_text_is_about_the_daemon_and_lists_the_models(self):
        import asyncio
        import chat_app
        import user_memory
        import tempfile

        async def inspect_app():
            user_memory.EVENTS = Path(tempfile.mkdtemp()) / "user.events.jsonl"
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return chat_app, app.identity_text()

        chat_app_module, text = asyncio.run(inspect_app())
        self.assertIn("Micronaut Daemon Bot", text)
        self.assertIn("Not ALICE", text)
        self.assertIn("Pop → Wo → Yax → Sek → Ch'en → Xul", text)
        for alias in chat_app_module.MODEL_REGISTRY:
            self.assertIn(alias, text, f"{alias} missing from the identity answer")
        self.assertIn("Advisors", text)
        # the mark is drawn in the answer, in a fenced block
        art = [line for line in text.splitlines() if set(line.strip()) and set(line.strip()) <= set("▀▄ ")]
        self.assertGreaterEqual(len(art), 8, "the mark should render as art rows")

    def test_identity_is_not_an_alice_answer(self):
        text = (ROOT / "identity.aiml").read_text(encoding="utf-8")
        self.assertIn("ARE YOU ALICE", text)
        for forbidden in ("ALICE is", "I am ALICE", "A.L.I.C.E."):
            self.assertNotIn(forbidden, text)

    def test_logo_box_is_smaller_than_a_poster(self):
        source = (ROOT / "chat_app.py").read_text(encoding="utf-8")
        row = re.search(r"#welcome-logo-row \{[^}]*height: (\d+)", source)
        logo = re.search(r"#welcome-logo \{[^}]*width: (\d+); height: (\d+)", source)
        self.assertIsNotNone(row)
        self.assertIsNotNone(logo)
        self.assertLessEqual(int(row.group(1)), 11, "the mark should not take more than 11 rows")
        self.assertLessEqual(int(logo.group(1)), 22)
        self.assertLessEqual(int(logo.group(2)), 11)

    def test_logo_png_is_downscaled(self):
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow is unavailable")
        with Image.open(ROOT / "logo.png") as image:
            self.assertLessEqual(image.size[0], 128, f"logo.png is {image.size}")
        self.assertLess((ROOT / "logo.png").stat().st_size, 40000, "logo.png is still heavy")


if __name__ == "__main__":
    unittest.main()
