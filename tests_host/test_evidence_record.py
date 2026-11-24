"""M43: inference evidence records - measure what the corpus saves, never invent what it doesn't.

Two rules under test:

**Measurements are measurements.** Latency is recorded only when observed; tokens are `None`, never 0,
when nobody counted them. The comparison reports `answer_quality: None` because no inference is run
there - a fabricated quality number would make the whole measurement useless.

**Records observe; they never admit.** Every record carries `admission.admitted: false` and
`authority: "declaration_only"`, and the log is chained through the ledger so it is tamper-evident.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evidence_record  # noqa: E402
import ledger_plugin  # noqa: E402

TASKS = ["tell me about my dog", "what changed", "explain quantum chromodynamics", "commit this"]


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.log = Path(self.folder.name) / "records.jsonl"

    def tearDown(self):
        self.folder.cleanup()

    def test_a_record_carries_every_observed_field(self):
        record = evidence_record.build(
            input_text="tell me about my dog",
            routing={"action": "chain", "closure": "delegated"},
            binding={"micronaut": "micronaut://v1/compose", "selected": None},
            retrieval={"categories": 3, "relations": 2}, operators=["filter", "map", "fold"],
            latency_ms=12.4)
        self.assertEqual(record["schema"], "kuhul-inference-record/1")
        for field in evidence_record.FIELDS:
            self.assertIn(field, record, field)
        self.assertEqual(record["closure"], "delegated")
        self.assertEqual(record["operators"], ["filter", "map", "fold"])
        self.assertEqual(record["retrieval"], {"categories": 3, "relations": 2})

    def test_latency_is_an_integer_because_the_log_is_chained(self):
        record = evidence_record.build(input_text="x", latency_ms=12.4)
        self.assertEqual(record["latency_ms"], 12)
        self.assertIsInstance(record["latency_ms"], int)
        with self.assertRaises(ledger_plugin.LedgerError):
            ledger_plugin.append({"kind": "x", "payload": {"latency_ms": 1.5}}, self.log)

    def test_unmeasured_values_are_none_not_zero(self):
        record = evidence_record.build(input_text="x")
        self.assertIsNone(record["latency_ms"])
        self.assertIsNone(record["tokens"])
        summary = evidence_record.summarise([record])
        self.assertIsNone(summary["tokens_total"])
        self.assertFalse(summary["tokens_measured"])
        self.assertIsNone(summary["latency_mean_ms"])

    def test_a_record_never_admits(self):
        record = evidence_record.build(input_text="x", routing={"action": "chain"})
        self.assertFalse(record["admission"]["admitted"])
        self.assertEqual(record["admission"]["authority"], "declaration_only")
        self.assertFalse(record["execution"])

    def test_an_unknown_closure_is_refused(self):
        with self.assertRaises(ValueError):
            evidence_record.build(input_text="x", routing={"action": "chain", "closure": "maybe"})

    def test_appending_chains_the_evidence_log(self):
        for index in range(3):
            evidence_record.append(evidence_record.build(input_text=f"turn {index}",
                                                         latency_ms=index + 1), self.log)
        report = evidence_record.verify(self.log)
        self.assertTrue(report["ok"], report["reasons"])
        self.assertEqual(report["entries"], 3)
        rows = evidence_record.load(self.log)
        self.assertEqual([row["latency_ms"] for row in rows], [1, 2, 3])

    def test_tampering_with_a_record_breaks_the_chain(self):
        evidence_record.append(evidence_record.build(input_text="a"), self.log)
        evidence_record.append(evidence_record.build(input_text="b"), self.log)
        lines = self.log.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["payload"]["input"] = "edited"
        lines[0] = json.dumps(record, sort_keys=True)
        self.log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertFalse(evidence_record.verify(self.log)["ok"])

    def test_a_summary_of_nothing_is_all_zero_and_null(self):
        summary = evidence_record.summarise([])
        self.assertEqual(summary["records"], 0)
        self.assertIsNone(summary["latency_mean_ms"])
        self.assertIsNone(summary["tokens_total"])


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparison = evidence_record.compare(TASKS)

    def test_the_corpus_handles_what_it_can(self):
        paths = self.comparison["paths"]
        self.assertEqual(paths["aiml_only"]["corpus_handled"], 1,
                         "only 'tell me about my dog' is resolved by the chain")
        self.assertEqual(paths["aiml_only"]["model_invocations"], 0,
                         "the corpus-only path never invokes a model")
        self.assertEqual(self.comparison["corpus_eliminated_model_calls"], 1)

    def test_the_model_paths_invoke_only_for_unhandled_turns(self):
        for name in ("aiml_worker", "aiml_advisor"):
            path = self.comparison["paths"][name]
            self.assertEqual(path["corpus_handled"], 1, name)
            self.assertEqual(path["model_invocations"], len(TASKS) - 1, name)

    def test_answer_quality_and_tokens_are_not_invented(self):
        for path in self.comparison["paths"].values():
            self.assertIsNone(path["answer_quality"], path["path"])
            self.assertIsNone(path["tokens"], path["path"])
        self.assertIn("no inference", self.comparison["note"])

    def test_every_path_records_its_measured_latency(self):
        for path in self.comparison["paths"].values():
            self.assertIsInstance(path["latency_ms"], int, path["path"])
            self.assertGreaterEqual(path["latency_ms"], 0)

    def test_the_comparison_is_deterministic(self):
        again = evidence_record.compare(TASKS)
        for name, path in self.comparison["paths"].items():
            self.assertEqual(path["corpus_handled"], again["paths"][name]["corpus_handled"])
            self.assertEqual(path["model_invocations"], again["paths"][name]["model_invocations"])

    def test_a_path_with_no_healthy_endpoint_reports_its_inability(self):
        comparison = evidence_record.compare(["explain quantum chromodynamics"],
                                             probes={"advisor": {"ok": False, "refused": "unreachable"},
                                                     "worker": {"ok": False, "refused": "unreachable"}})
        worker = comparison["paths"]["aiml_worker"]
        self.assertEqual(worker["model_invocations"], 0)
        self.assertEqual(worker["route_ok"], 0)
        self.assertFalse(worker["rows"][0]["route_ok"])


if __name__ == "__main__":
    unittest.main()
