"""M20: Greeting-µ - the greeting graph is loaded data, and it keeps every intent in a message.

`greeting.gml` declares greetings, social questions, destinations, the paths between them, and the
authority each destination needs. This module applies that document; it never executes anything and
never authorizes anything.

The rules under test:

  graph is data      editing greeting.gml changes what is recognised (a mutation test, not a promise)
  multi-intent       "Hey, how are you, and can you check my server?" keeps all three intents
  remainder          a greeting that opens a longer clause keeps what followed it
  no authority       every candidate carries the authority the graph declares, never a grant
  all-or-nothing     a clause that cannot be answered locally hands the whole utterance on
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402
import greetings  # noqa: E402

EXAMPLE = "Hey, how are you, and can you check my server?"


class M20GreetingGraph(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.folder.cleanup()

    # -- the document ---------------------------------------------------------------------------
    def test_graph_loads_and_is_well_formed(self):
        loaded = greetings.load()
        self.assertTrue(loaded["ok"], loaded["problems"])
        self.assertEqual(loaded["schema"], "gml-conversation/1")
        self.assertEqual(loaded["graph_id"], "conversation/greeting")
        self.assertEqual(loaded["counts"], dict(nodes=14, edges=21))

    def test_every_destination_declares_a_valid_authority(self):
        destinations = greetings.destinations()
        self.assertEqual(len(destinations), 7, sorted(destinations))
        self.assertEqual(destinations["command"]["authority"], "requires_grant")
        self.assertEqual(destinations["memory"]["authority"], "requires_grant")
        self.assertEqual(destinations["tool"]["authority"], "proposal_only")
        self.assertEqual(destinations["conversation"]["authority"], "read_only")

    def test_a_greeting_reaches_the_whole_system(self):
        reachable = greetings.reachable("HEY")
        for destination in ("conversation", "question", "tool", "command", "memory", "task", "identity"):
            self.assertIn(destination, reachable)

    def test_the_document_is_load_bearing(self):
        """Add a greeting to a copy of the graph and it must be recognised - no Python list to edit."""
        copy = Path(self.folder.name) / "greeting.gml"
        shutil.copy(ROOT / "greeting.gml", copy)
        text = copy.read_text(encoding="utf-8")
        text = text.replace('  node [ id 5 kind "greeting" phrase "YO" meaning "open contact, very informal" ]',
                            '  node [ id 5 kind "greeting" phrase "YO" meaning "open contact, very informal" ]\n'
                            '  node [ id 15 kind "greeting" phrase "SUP" meaning "added by the test" ]', 1)
        self.assertNotIn("SUP", greetings.phrases("greeting", copy.parent / "greeting.gml"))
        copy.write_text(text, encoding="utf-8")
        self.assertIn("SUP", greetings.phrases("greeting", copy))
        self.assertEqual(greetings.classify("SUP", copy)["kind"], "greeting")

    # -- decomposition --------------------------------------------------------------------------
    def test_the_example_keeps_all_three_intents(self):
        routes = greetings.routes(EXAMPLE)
        self.assertTrue(routes["multi"])
        self.assertEqual([intent["kind"] for intent in routes["intents"]],
                         ["greeting", "social", "destination"])
        self.assertEqual([intent["destination"] for intent in routes["intents"]],
                         ["conversation", "conversation", "tool"])
        self.assertEqual(routes["intents"][2]["authority"], "proposal_only")
        self.assertIs(routes["authorized"], False, "a graph may route; it may not authorize")

    def test_a_greeting_remainder_becomes_its_own_intent(self):
        routes = greetings.routes("hey remember my dogs name is max")
        self.assertEqual(len(routes["intents"]), 2)
        self.assertEqual(routes["intents"][0]["kind"], "greeting")
        self.assertEqual(routes["intents"][1]["destination"], "memory")
        self.assertEqual(routes["intents"][1]["authority"], "requires_grant")

    def test_connectors_do_not_become_clauses(self):
        self.assertEqual(greetings.split("hello and then git status"),
                         ["hello", "git status"])
        self.assertEqual(greetings.split("hi, and can you check the diff"),
                         ["hi", "can you check the diff"])

    def test_commands_and_tasks_are_recognised(self):
        self.assertEqual(greetings.classify("commit this")["destination"], "command")
        self.assertEqual(greetings.classify("push it")["destination"], "command")
        self.assertEqual(greetings.classify("add task fix the header")["destination"], "task")
        self.assertEqual(greetings.classify("who are you")["destination"], "identity")

    # -- the host ------------------------------------------------------------------------------
    def test_the_host_answers_a_multi_intent_message_in_full(self):
        import asyncio
        import session_log
        import user_memory

        async def drive(text):
            session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
            user_memory.EVENTS = Path(tempfile.mkdtemp()) / "user.events.jsonl"
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return app.local_answer(text)

        local = asyncio.run(drive("hi there, what is the time"))
        self.assertIsNotNone(local, "both clauses are answerable locally")
        kind, body = local
        self.assertEqual(kind, "aiml")
        self.assertIn("conversation", body)
        self.assertIn("question", body)
        self.assertIn(":", body, "the time answer should be present")

    def test_an_unanswerable_clause_hands_the_whole_message_on(self):
        import asyncio
        import session_log
        import user_memory

        async def drive(text):
            session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
            user_memory.EVENTS = Path(tempfile.mkdtemp()) / "user.events.jsonl"
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return app.local_answer(text)

        self.assertIsNone(asyncio.run(drive(EXAMPLE)),
                          "half an answer is worse than an honest handoff")

    def test_a_single_greeting_is_unchanged(self):
        import asyncio
        import session_log
        import user_memory

        async def drive():
            session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
            user_memory.EVENTS = Path(tempfile.mkdtemp()) / "user.events.jsonl"
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return app.local_answer("hello")

        kind, body = asyncio.run(drive())
        self.assertEqual(kind, "aiml")
        self.assertNotIn("---", body, "one intent is not a sectioned answer")


if __name__ == "__main__":
    unittest.main()
