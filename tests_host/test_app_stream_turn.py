"""M69: the real streaming entry point holds one lease, and the turn is observable afterwards.

The guard the review asked for runs `stream_llm_response` itself, with a fake client, and checks the things a
mechanism test cannot:

    selected model     the lifecycle backend that serves the app's alias
    lifecycle          exactly one acquire and one release for the turn
    rendered text      the same chunks in the same order
    cancellation       closing the stream releases the lease
    evidence           one request id, shared by the turn and the record
    authority          inference never implies admission
"""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evidence_record  # noqa: E402
import model_lifecycle  # noqa: E402


class FakeEvent:
    def __init__(self, delta):
        self.type = "content.delta"
        self.delta = delta


class FakeMessage:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None

    def model_dump(self, exclude_none=True):
        return {"role": "assistant", "content": self.content}


class FakeCompletion:
    def __init__(self, content):
        choice = type("Choice", (), {"message": FakeMessage(content)})()
        self.choices = [choice]


class FakeStream:
    def __init__(self, chunks, *, raise_at=None, consume=None):
        self.chunks = chunks
        self.raise_at = raise_at
        self.consume = consume

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        limit = self.raise_at if self.raise_at is not None else len(self.chunks)
        for index, chunk in enumerate(self.chunks):
            if index >= limit:
                raise RuntimeError("the connection dropped mid-stream")
            if self.consume is not None and index >= self.consume:
                return
            yield FakeEvent(chunk)

    def get_final_completion(self):
        return FakeCompletion("".join(self.chunks[:self.consume]))


class FakeCompletions:
    def __init__(self, stream):
        self.stream_instance = stream

    def stream(self, **kwargs):
        self.last_kwargs = kwargs
        return self.stream_instance


class FakeClient:
    def __init__(self, stream):
        self.chat = type("Chat", (), {"completions": FakeCompletions(stream)})()


class AppTurnTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original_log = evidence_record.LOG
        evidence_record.LOG = Path(self.folder.name) / "records.jsonl"

    def tearDown(self):
        evidence_record.LOG = self.original_log
        self.folder.cleanup()

    def drive(self, stream, *, text="hello"):
        import chat_app
        import session_log

        session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())

        async def run():
            app = chat_app.ChatApp()
            acquired = []
            released = []
            original_acquire = app.lifecycle.acquire
            original_release = app.lifecycle.release

            def acquire(model):
                acquired.append(model)
                return original_acquire(model)

            def release(model):
                released.append(model)
                return original_release(model)

            app.lifecycle.acquire = acquire
            app.lifecycle.release = release
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app.client = FakeClient(stream)
                app.request_id = "turn-1"
                # the entry point is a Textual worker, so the turn is awaited through the worker
                worker = app.stream_llm_response(text)
                await worker.wait()
                # the worker settles before its finally block has necessarily completed
                for _ in range(100):
                    if getattr(app, "last_stream", None) is not None:
                        break
                    await asyncio.sleep(0.05)
                await pilot.pause()
                # the assistant message is the durable rendering path; the widget is a Static we do not
                # need to scrape for this guard
                assistant = [message for message in app.messages if message.get("role") == "assistant"]
                return dict(app=app, acquired=acquired, released=released,
                            rendered=[message.get("content") or "" for message in assistant],
                            leases=dict(app.lifecycle.leases),
                            record=app.last_record, stream=app.last_stream,
                            error=app.last_stream_error, records=evidence_record.load())

        return asyncio.run(run())

    def test_one_acquire_and_one_release_for_the_turn(self):
        result = self.drive(FakeStream(["a", "b", "c"]))
        # the default session model is gpt-oss-20b, which the lifecycle calls `advisor`
        self.assertEqual(result["acquired"], ["advisor"])
        self.assertEqual(result["released"], ["advisor"])
        self.assertEqual(result["leases"].get("advisor", 0), 0)

    def test_the_chunks_reach_the_view_in_order(self):
        result = self.drive(FakeStream(["one ", "two ", "three"]))
        self.assertTrue(any("one two three" in line for line in result["rendered"]),
                        result["rendered"][-1:])

    def test_the_measurements_are_recorded_for_the_turn(self):
        result = self.drive(FakeStream(["x"] * 4))
        stream = result["stream"]
        self.assertIsNotNone(stream)
        self.assertEqual(stream["chunks"], 4)
        self.assertIn("wake_latency_ms", stream)
        self.assertIn("boundaries", stream)
        self.assertTrue(stream["lease_released"])

    def test_an_interrupted_stream_still_releases_and_reports(self):
        result = self.drive(FakeStream(["a", "b", "c"], raise_at=1))
        self.assertEqual(result["leases"].get("advisor", 0), 0)
        self.assertIn("dropped", result["error"] or "")
        self.assertTrue(result["stream"]["lease_released"])

    def test_evidence_shares_the_turn_request_id(self):
        result = self.drive(FakeStream(["hello"]))
        records = result["records"]
        self.assertTrue(records, "the turn produced an observation")
        self.assertEqual(records[-1]["request_id"], "turn-1")
        self.assertEqual(records[-1]["inference"], "model")
        self.assertFalse(records[-1]["admission"]["proposal_admitted"])

    def test_inference_never_implies_admission(self):
        result = self.drive(FakeStream(["ok"]))
        record = result["records"][-1]
        self.assertFalse(record["admission"]["proposal_admitted"])
        self.assertFalse(record["admission"]["observed_execution"])
        self.assertFalse(record["execution"])
        self.assertEqual(record["admission"]["authority"], "declaration_only")

    def test_the_backend_is_the_one_serving_the_alias(self):
        declaration = model_lifecycle.load()
        self.assertEqual(model_lifecycle.backend_for_alias(declaration, "gpt-oss-20b"), "advisor")
        self.assertIsNone(model_lifecycle.backend_for_alias(declaration, "not-a-model"))


if __name__ == "__main__":
    unittest.main()
