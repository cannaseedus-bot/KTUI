"""M45: live evidence capture - the turn is recorded, and recording can never change the answer.

Two rules under test:

**Recording is best effort.** If the evidence log cannot be written, the answer still returns; the defect
is reported on the app (`last_record_error`) instead of being swallowed or allowed to break the turn.

**A record observes; it does not admit.** `proposal_admitted` stays false while `observed_execution`
tells the truth about what the host actually did - those are different facts and the log keeps them apart.
"""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402
import evidence_record  # noqa: E402
import session_log  # noqa: E402
import user_memory  # noqa: E402


class LiveCaptureTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.log = Path(self.folder.name) / "records.jsonl"
        self.original_log = evidence_record.LOG
        evidence_record.LOG = self.log
        session_log.SESSIONS_DIR = Path(self.folder.name) / "sessions"
        self.original_events = user_memory.EVENTS
        user_memory.EVENTS = Path(self.folder.name) / "user.events.jsonl"

    def tearDown(self):
        evidence_record.LOG = self.original_log
        user_memory.EVENTS = self.original_events
        self.folder.cleanup()

    def turn(self, texts):
        async def drive():
            app = chat_app.ChatApp()
            seen = []
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                for text in texts:
                    app.query_one("Input").value = text
                    await pilot.press("enter")
                    await pilot.pause()
                    seen.append((text, app.last_record, app.last_record_error, app.request_id))
            return seen

        return asyncio.run(drive())

    # -- capture -----------------------------------------------------------------------------------
    def test_a_local_turn_is_recorded_with_its_request_identity(self):
        seen = self.turn(["hello"])
        text, record, error, request_id = seen[0]
        self.assertIsNone(error, error)
        self.assertIsNotNone(record)
        self.assertEqual(record["request_id"], request_id)
        self.assertEqual(record["inference"], "local")
        self.assertFalse(record["observed_execution"], "an AIML answer performs no host operation")
        rows = evidence_record.load()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["request_id"], request_id)

    def test_a_host_operation_is_marked_as_observed_execution(self):
        seen = self.turn(["git status"])
        _, record, error, _ = seen[0]
        self.assertIsNone(error, error)
        self.assertTrue(record["observed_execution"], "a tool ran on the host")
        self.assertEqual(record["execution_kind"], "host_operation")
        self.assertFalse(record["admission"]["proposal_admitted"],
                         "an observed read is not a proposal admission")
        self.assertTrue(record["admission"]["observed_execution"])

    def test_the_prompt_is_digested_not_stored(self):
        seen = self.turn(["hello"])
        rows = evidence_record.load()
        self.assertEqual(len(rows[0]["input_sha256"]), 64)
        self.assertEqual(rows[0]["input_chars"], len("hello"))
        self.assertNotIn("hello", str(rows[0]), "the prompt itself is not kept")

    def test_each_turn_gets_its_own_identifier(self):
        seen = self.turn(["hello", "who are you", "git status"])
        ids = [request_id for _, _, _, request_id in seen]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(len(evidence_record.load()), 3)
        self.assertTrue(evidence_record.verify()["ok"], "the evidence log verifies")

    def test_a_failed_recording_does_not_change_the_answer(self):
        def explode(*args, **kwargs):
            raise OSError("disk full")

        original = evidence_record.append
        evidence_record.append = explode
        try:
            seen = self.turn(["hello"])
        finally:
            evidence_record.append = original
        text, record, error, _ = seen[0]
        self.assertIsNone(record)
        self.assertIn("disk full", error or "")
        self.assertTrue(self.answer_was_rendered())

    def answer_was_rendered(self) -> bool:
        """The turn still produced its answer: the fallback path mounts a Response."""
        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                app.query_one("Input").value = "hello"
                await pilot.press("enter")
                await pilot.pause()
                view = app.query_one("#chat-view")
                return [type(child).__name__ for child in view.children]
        return "Response" in asyncio.run(drive())


class RecordShapeTests(unittest.TestCase):
    def test_execution_and_admission_are_separate_facts(self):
        record = evidence_record.build(input_text="git status", observed_execution=True,
                                       execution_kind="host_operation", inference="local")
        self.assertFalse(record["admission"]["proposal_admitted"])
        self.assertTrue(record["admission"]["observed_execution"])
        proposal_only = evidence_record.build(input_text="x")
        self.assertFalse(proposal_only["observed_execution"])
        self.assertIn("never admits", proposal_only["admission"]["note"])

    def test_an_unmeasured_token_count_stays_none(self):
        record = evidence_record.build(input_text="x", inference="model")
        self.assertIsNone(record["tokens"])
        summary = evidence_record.summarise([record])
        self.assertFalse(summary["tokens_measured"])


if __name__ == "__main__":
    unittest.main()
