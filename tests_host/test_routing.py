"""M15: routing honesty - local answers stay local, refusals explain themselves.

The bug this guards against was silent: a policy refusal (a memory write without the grant) returned
no local answer, so the turn was handed to the model, which then improvised a response. A refusal is
an answer. And no turn kind may crash the renderer, which is what a three-key heading table did.

Also asserted here: a genuine no-match *should* reach the model - the point is not to answer
everything locally, it is to know which turns are which.
"""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402
import daemon  # noqa: E402
import session_log  # noqa: E402
import user_memory  # noqa: E402

LOCAL_CASES = ("who are you", "what is the time", "my dogs name is max")


class M15RoutingHonesty(unittest.TestCase):
    def test_refusal_is_a_local_answer_not_a_handoff(self):
        kernel = __import__("aiml").Kernel()
        kernel.learn(str(ROOT / "memory.aiml"))
        engine = daemon.Daemon(kernel=lambda text: kernel.respond(text), banks=[],
                               admit=lambda verb, arg: (True, "read-only"),
                               admit_plan=lambda name: (False, "no plans"),
                               admit_memory=lambda kind, arg: (False, "memory writes need /allow memory"))
        turn = engine.run("my dogs name is max")
        self.assertEqual(turn.kind, "refused")
        self.assertIn("memory writes need", turn.answer)
        self.assertIn("refused", str(dict(turn.phases).get("Ch'en", "")))

    def test_local_turns_render_without_a_heading_crash(self):
        """Every kind the app can return must have a heading; a KeyError here would bounce to the model."""
        async def drive():
            session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
            user_memory.EVENTS = Path(tempfile.mkdtemp()) / "user.events.jsonl"
            app = chat_app.ChatApp()
            rendered = []
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                for phrase in LOCAL_CASES:
                    box = app.query_one("#chat-view")
                    before = len(box.children)
                    app.query_one("Input").value = phrase
                    await pilot.press("enter")
                    await pilot.pause()
                    new = box.children[before:]
                    rendered.append((phrase, len(new), [type(child).__name__ for child in new]))
                    self.assertEqual(app.query_one("Input").value, "", phrase)
            return rendered

        rendered = asyncio.run(drive())
        for phrase, count, kinds in rendered:
            self.assertGreaterEqual(count, 2, f"{phrase} produced no prompt+response pair ({kinds})")
            self.assertIn("Response", kinds, f"{phrase} rendered no Response ({kinds})")

    def test_greetings_are_answered_locally(self):
        """A greeting must not cost a model round trip, and must not print a routing notice."""
        async def ask():
            session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
            user_memory.EVENTS = Path(tempfile.mkdtemp()) / "user.events.jsonl"
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return [(phrase, app.local_answer(phrase))
                        for phrase in ("hello", "hi", "thanks", "bye", "how are you")]

        for phrase, local in asyncio.run(ask()):
            self.assertIsNotNone(local, f"{phrase!r} fell through to the model")
            kind, body = local
            self.assertEqual(kind, "aiml", f"{phrase!r} was not answered from the bank")
            self.assertTrue(str(body).strip(), f"{phrase!r} produced an empty answer")

    def test_unknown_phrase_reaches_the_model_with_a_reason(self):
        async def check():
            session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                local = app.local_answer("explain quantum chromodynamics")
                return local, app.routing_note()

        local, note = asyncio.run(check())
        self.assertIsNone(local, "a genuine no-match should be handed to the model")
        self.assertIn("model", note.lower())
        self.assertTrue(note.strip())


if __name__ == "__main__":
    unittest.main()
