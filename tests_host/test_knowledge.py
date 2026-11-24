"""M22: the daemon knows things locally, and offers depth instead of guessing at it.

Two behaviours are under test.

**Knowledge is learned.** The curated ALICE banks answer "what is Saturn" without a model round trip,
and the host's own banks still win over the corpus: greetings, identity, memory and git look nothing
like a corpus answer. There is deliberately no catch-all bank in the set, so a genuine unknown still
defers honestly.

**Depth is offered, not spent.** A short factual answer ends with an offer; saying yes sends the
*original question* to the model rather than the word "yes", and anything else cancels the offer. A
greeting, an identity answer, a tool result or a refusal never offers depth, because there is nothing
to deepen.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402
import knowledge  # noqa: E402
import session_log  # noqa: E402
import user_memory  # noqa: E402

OFFER = "delve deeper"


class M22KnowledgeAndDepth(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
        user_memory.EVENTS = Path(self.folder.name) / "user.events.jsonl"

    def tearDown(self):
        self.folder.cleanup()

    def app_with_recorder(self):
        app = chat_app.ChatApp()
        calls = []
        app.stream_llm_response = lambda text: calls.append(text)
        return app, calls

    # -- the knowledge set -----------------------------------------------------------------
    def test_the_knowledge_set_is_bounded_and_present(self):
        paths = knowledge.paths()
        self.assertEqual(len(paths), 21, [path.name for path in paths])
        self.assertTrue(all(path.is_file() for path in paths))
        summary = knowledge.summary()
        self.assertEqual(summary["missing"], [])
        for name in ("default", "that", "update1"):
            self.assertIn(name, summary["excluded"])

    def test_knowledge_can_be_disabled_for_a_session(self):
        previous = os.environ.get("KNUMATIC_KNOWLEDGE")
        try:
            os.environ["KNUMATIC_KNOWLEDGE"] = "off"
            self.assertEqual(knowledge.paths(), [])
            self.assertFalse(knowledge.enabled())
        finally:
            if previous is None:
                os.environ.pop("KNUMATIC_KNOWLEDGE", None)
            else:
                os.environ["KNUMATIC_KNOWLEDGE"] = previous

    def test_a_knowledge_question_is_answered_locally(self):
        async def ask():
            app, calls = self.app_with_recorder()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return app.local_answer("what is saturn"), app, calls

        local, app, calls = asyncio.run(ask())
        self.assertIsNotNone(local, "the knowledge banks should answer this without the model")
        kind, body = local
        self.assertEqual(kind, "aiml")
        self.assertIn("planet", body.lower())
        self.assertEqual(calls, [], "no model call for a locally known fact")
        self.assertEqual(app.pending_deep, "what is saturn")

    # -- the offer -------------------------------------------------------------------------
    def test_a_factual_answer_offers_depth(self):
        async def ask():
            app, _ = self.app_with_recorder()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return app.local_answer("what is saturn")

        kind, body = asyncio.run(ask())
        self.assertIn(OFFER, body.lower())

    def test_the_offer_can_be_disabled(self):
        async def ask():
            app, _ = self.app_with_recorder()
            app.offer_deepening = False
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return app.local_answer("what is saturn"), app

        local, app = asyncio.run(ask())
        self.assertNotIn(OFFER, local[1].lower())
        self.assertIsNone(app.pending_deep)

    def test_tool_identity_and_refusals_do_not_offer_depth(self):
        async def ask(phrase):
            app, _ = self.app_with_recorder()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return app.local_answer(phrase), app

        for phrase in ("what is the time", "who are you", "hello", "commit this"):
            local, app = asyncio.run(ask(phrase))
            self.assertIsNotNone(local, phrase)
            self.assertNotIn(OFFER, local[1].lower(), phrase)
            self.assertIsNone(app.pending_deep, phrase)

    # -- accepting the offer ---------------------------------------------------------------
    def test_yes_sends_the_original_question_to_the_model(self):
        async def drive():
            app, calls = self.app_with_recorder()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                app.local_answer("what is saturn")
                app.query_one("Input").value = "yes"
                await pilot.press("enter")
                await pilot.pause()
                return calls, app.pending_deep

        calls, pending = asyncio.run(drive())
        self.assertEqual(calls, ["what is saturn"],
                         "the model must receive the question, not the word 'yes'")
        self.assertIsNone(pending)

    def test_any_other_message_cancels_the_offer(self):
        async def drive():
            app, calls = self.app_with_recorder()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                app.local_answer("what is saturn")
                app.query_one("Input").value = "what is the time"
                await pilot.press("enter")
                await pilot.pause()
                return calls, app.pending_deep

        calls, pending = asyncio.run(drive())
        self.assertEqual(calls, [], "a different question must not trigger the model")
        self.assertIsNone(pending)

    def test_unmatched_phrases_still_defer_to_the_model(self):
        async def ask():
            app, _ = self.app_with_recorder()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return app.local_answer("explain quantum chromodynamics"), app

        local, app = asyncio.run(ask())
        self.assertIsNone(local, "no catch-all bank may answer everything")
        self.assertIsNone(app.pending_deep)


if __name__ == "__main__":
    unittest.main()
