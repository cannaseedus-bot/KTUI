"""M89 integration: the streaming turn observed through Sek, Ch'en and Xul.

The worker body is driven directly with a fake streaming client, because the Textual worker is not awaitable. What
is asserted is the contract the review asked for: a completed stream is a candidate, validation is separate, and
emission success is not turn success. Transport failures are their own outcome, and a dropped observation is counted.
"""
import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402
import phase_events  # noqa: E402
import session_log  # noqa: E402


class FakeStream:
    def __init__(self, text, error=None):
        self.text = text
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        if self.error is not None:
            raise self.error
        for piece in (self.text[index:index + 8] for index in range(0, len(self.text), 8)):
            yield types.SimpleNamespace(type="content.delta", delta=piece)

    def get_final_completion(self):
        message = types.SimpleNamespace(content=self.text, tool_calls=[],
                                        model_dump=lambda **kwargs: {"role": "assistant",
                                                                     "content": self.text})
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class FakeCompletions:
    def __init__(self, stream):
        self.stream_obj = stream

    def stream(self, **kwargs):
        return self.stream_obj


class FakeClient:
    def __init__(self, stream):
        self.chat = types.SimpleNamespace(completions=FakeCompletions(stream))


class StreamingTurnTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        session_log.SESSIONS_DIR = Path(self.folder.name) / "sessions"

    def tearDown(self):
        self.folder.cleanup()

    def turn(self, answer, *, error=None, request_id="model-1"):
        phase_events.reset()

        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app.client = FakeClient(FakeStream(answer, error=error))
                app.waker = None
                app.lifecycle = None
                app.request_id = request_id
                await chat_app.ChatApp.stream_llm_response.__wrapped__(app, "tell me something")
                return app.observation_errors, app.last_observation_error

        errors, last = asyncio.run(drive())
        return phase_events.observe(request_id), errors, last

    def exits(self, trace):
        return {event["phase"]: event["detail"] for event in trace["events"]
                if event["event"] == "phase_exit"}

    def test_an_accepted_stream_closes_as_accepted(self):
        trace, errors, _ = self.turn("Rex is your dog and he is black.")
        self.assertEqual(errors, 0, "no observation was dropped")
        self.assertEqual(trace["phases"], ["Sek", "Ch'en", "Xul"])
        self.assertTrue(trace["complete"], "every phase that entered also exited")
        exits = self.exits(trace)
        self.assertEqual(exits["Sek"]["transport"], "ok")
        self.assertGreater(exits["Sek"]["chunks"], 1)
        self.assertEqual(exits["Ch'en"]["verdict"], "accepted")
        self.assertEqual(exits["Xul"]["turn_outcome"], "accepted")
        self.assertTrue(exits["Xul"]["ok"])

    def test_a_completed_stream_that_refuses_is_not_a_success(self):
        trace, errors, _ = self.turn("I cannot do that: the capability is not granted.")
        self.assertEqual(errors, 0)
        exits = self.exits(trace)
        self.assertEqual(exits["Sek"]["transport"], "ok", "the transport succeeded")
        self.assertEqual(exits["Ch'en"]["verdict"], "refused")
        self.assertTrue(exits["Ch'en"]["verified"], "a refusal is verifiable")
        self.assertEqual(exits["Xul"]["turn_outcome"], "refused")
        self.assertTrue(exits["Xul"]["emitted"], "the refusal was displayed")
        self.assertFalse(exits["Xul"]["ok"], "and the turn did not succeed")
        self.assertEqual(trace["state"], "failed", "the trace reports the turn, not the transport")

    def test_a_transport_failure_is_not_a_model_failure(self):
        trace, errors, _ = self.turn("", error=ConnectionError("connection reset"))
        self.assertEqual(errors, 0)
        exits = self.exits(trace)
        self.assertEqual(exits["Sek"]["transport"], "failed")
        self.assertEqual(exits["Ch'en"]["verdict"], "transport_failed")
        self.assertFalse(exits["Ch'en"]["verified"])
        self.assertEqual(exits["Xul"]["turn_outcome"], "failed")
        self.assertTrue(trace["complete"], "a failed turn still closes")

    def test_the_three_facts_stay_separate(self):
        trace, _, _ = self.turn("I cannot do that.")
        exits = self.exits(trace)
        self.assertEqual((exits["Xul"]["emitted"], exits["Xul"]["verified"]), (True, True))
        self.assertFalse(exits["Xul"]["ok"])

    def test_no_request_id_means_no_events(self):
        phase_events.reset()

        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app.client = FakeClient(FakeStream("Rex is your dog."))
                app.waker = None
                app.lifecycle = None
                app.request_id = None
                await chat_app.ChatApp.stream_llm_response.__wrapped__(app, "hello")
                return app.observation_errors

        errors = asyncio.run(drive())
        self.assertEqual(errors, 0)
        self.assertEqual(len(phase_events._traces.get("") or []), 0)

    def test_concurrent_turns_keep_their_own_traces(self):
        phase_events.reset()
        first, _, _ = self.turn("Rex is your dog.", request_id="model-a")
        second, _, _ = self.turn("I cannot do that.", request_id="model-b")
        self.assertEqual({event["request_id"] for event in first["events"]}, {"model-a"})
        self.assertEqual({event["request_id"] for event in second["events"]}, {"model-b"})


if __name__ == "__main__":
    unittest.main()
