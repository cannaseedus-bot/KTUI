"""M12: user memory - proposals in, admitted writes out, JSONL history, GML projection.

The architecture claim under test:

  a matching AIML pattern proposes a memory operation; the host admits it; the JSONL event log keeps
  the history; the GML projection relates it; queries read the projection.

Each test names the rule it protects: recognition is not authority, corrections append, isolation is
per identity, erasure beats append-only history, and the projection is a view that validates.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aiml  # noqa: E402
import daemon  # noqa: E402
import ledger_plugin  # noqa: E402
import user_memory  # noqa: E402


class M12UserMemory(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.events = Path(self.folder.name) / "user.events.jsonl"

    def tearDown(self):
        self.folder.cleanup()

    # recognition is not authority
    def test_aiml_proposes_and_writes_nothing(self):
        kernel = aiml.Kernel()
        kernel.learn(str(ROOT / "memory.aiml"))
        self.assertEqual(kernel.respond("MY DOGS NAME IS MAX"), "MEMORY remember pet.name MAX")
        self.assertEqual(kernel.respond("WHAT IS MY DOGS NAME"), "MEMQUERY pet.name")
        self.assertEqual(kernel.respond("ERASE MY MEMORY"), "MEMORY erase")
        self.assertEqual(user_memory.events(path=self.events), [], "a pattern must not write")

    def test_daemon_routes_memory_through_admission(self):
        kernel = aiml.Kernel()
        kernel.learn(str(ROOT / "memory.aiml"))
        decisions = []

        def admit_memory(kind, argument):
            decisions.append((kind, argument))
            return (kind == "memquery"), f"{kind} {'read-only' if kind == 'memquery' else 'refused'}"

        engine = daemon.Daemon(kernel=lambda text: kernel.respond(text), banks=[],
                               admit=lambda verb, arg: (True, "read-only"),
                               admit_plan=lambda name: (False, "none"),
                               admit_memory=admit_memory)
        read = engine.run("what is my dogs name")
        self.assertEqual(read.kind, "memquery")
        self.assertEqual(read.answer, "pet.name")
        write = engine.run("my dogs name is max")
        self.assertEqual(write.kind, "deferred", "a refused write must not become a turn")
        self.assertEqual(decisions[0][0], "memquery")
        self.assertEqual(decisions[1][0], "memory")

    # admitted writes and the projection
    def test_remember_then_query(self):
        event = user_memory.remember(user="alice", subject="pet", predicate="name", value="Max",
                                     path=self.events)
        self.assertEqual(event["event_id"], "evt-000000")
        self.assertEqual(user_memory.projection("alice", self.events)["pet"]["name"], "Max")
        self.assertIn("Max", user_memory.answer("alice", "pet", "name", self.events))

    def test_correction_appends_and_the_projection_follows(self):
        user_memory.remember(user="alice", subject="pet", predicate="name", value="Max", path=self.events)
        user_memory.remember(user="alice", subject="pet", predicate="name", value="Rex", path=self.events)
        rows = user_memory.events("alice", self.events)
        self.assertEqual(len(rows), 2, "a correction must append, never rewrite")
        self.assertEqual([row["payload"]["value"] for row in rows], ["Max", "Rex"])
        self.assertEqual(user_memory.projection("alice", self.events)["pet"]["name"], "Rex")

    def test_forget_retracts_without_deleting_history(self):
        user_memory.remember(user="alice", subject="pet", predicate="name", value="Max", path=self.events)
        user_memory.forget(user="alice", subject="pet", predicate="name", path=self.events)
        self.assertEqual(user_memory.projection("alice", self.events), {})
        self.assertEqual(len(user_memory.events("alice", self.events)), 2)

    # isolation
    def test_users_are_isolated(self):
        user_memory.remember(user="alice", subject="pet", predicate="name", value="Max", path=self.events)
        user_memory.remember(user="bob", subject="pet", predicate="name", value="Rex", path=self.events)
        self.assertEqual(user_memory.projection("alice", self.events)["pet"]["name"], "Max")
        self.assertEqual(user_memory.projection("bob", self.events)["pet"]["name"], "Rex")
        self.assertNotIn("bob", str(user_memory.graph("alice", self.events)))

    # the projection is a view that validates
    def test_graph_projection_validates(self):
        user_memory.remember(user="alice", subject="pet", predicate="name", value="Max", path=self.events)
        user_memory.remember(user="alice", subject="pet", predicate="personality", value="playful",
                             path=self.events)
        document = user_memory.graph("alice", self.events)
        check = user_memory.validate(document)
        self.assertTrue(check["ok"], check["problems"])
        self.assertEqual(check["schema_source"], "memory.gml")
        self.assertGreaterEqual(check["edges"], 3)
        broken = dict(document, edges=document["edges"] + [dict(source=0, target=99, relation="ghost")])
        self.assertFalse(user_memory.validate(broken)["ok"])

    # erasure beats append-only history
    def test_erase_compacts_and_leaves_a_tombstone(self):
        user_memory.remember(user="alice", subject="pet", predicate="name", value="Max", path=self.events)
        user_memory.remember(user="alice", subject="pet", predicate="name", value="Rex", path=self.events)
        user_memory.remember(user="bob", subject="pet", predicate="name", value="Fido", path=self.events)
        outcome = user_memory.erase("alice", self.events)
        self.assertEqual(outcome["removed"], 2)
        self.assertEqual(user_memory.projection("alice", self.events), {})
        self.assertEqual(user_memory.projection("bob", self.events)["pet"]["name"], "Fido")
        tail = user_memory.events(path=self.events)[-1]
        self.assertEqual(tail["kind"], "memory:erasure")
        self.assertEqual(tail["payload"]["user_id"], "alice")

    # the history is chained, like the audit ledger
    def test_history_is_tamper_evident(self):
        user_memory.remember(user="alice", subject="pet", predicate="name", value="Max", path=self.events)
        user_memory.remember(user="alice", subject="pet", predicate="name", value="Rex", path=self.events)
        report = ledger_plugin.verify(self.events)
        self.assertTrue(report["ok"], report["reasons"])
        self.assertEqual(report["entries"], 2)
        lines = self.events.read_text(encoding="utf-8").splitlines()
        record = __import__("json").loads(lines[0])
        record["payload"]["value"] = "Tampered"
        lines[0] = __import__("json").dumps(record, sort_keys=True)
        self.events.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertFalse(ledger_plugin.verify(self.events)["ok"])


if __name__ == "__main__":
    unittest.main()
