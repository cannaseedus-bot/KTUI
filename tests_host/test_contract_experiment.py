"""M52: one operator contract, rendered into the prompt and enforced by the validator.

The guards here are about the *protocol*, because M51 showed how easily a comparison can be spoiled:

    one system prompt                  identical in both conditions, and recorded in the result
    the baseline is frozen             its suffix is a constant in the module, above the results
    the contract comes from the file   change `operators.json` and the prompt changes with it
    repeats, not one run               sampling noise is measured instead of assumed away
    exact graph equivalence            the only success criterion; no partial credit
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import contract_experiment  # noqa: E402
import evaluation_harness  # noqa: E402
import plan_graph  # noqa: E402

CONTRACTED = ["filter", "map", "fold", "reduce"]
AMBIGUOUS = ["filter", "map", "accumulate", "reduce"]


def reply(operators):
    return dict(text=json.dumps({"phase": "Sek", "operators": operators, "authority": "proposal"}),
                model="stub", completion_tokens=40, latency_ms=12, finish_reason="stop")


class ContractDocumentTests(unittest.TestCase):
    def test_the_contract_loads_and_matches_the_grammar(self):
        loaded = plan_graph.contract()
        self.assertTrue(loaded["ok"], loaded["problems"])
        self.assertEqual(loaded["uri"], "kuhul://operators/v1")
        self.assertEqual(loaded["record"]["execution_order"], list(plan_graph.CANONICAL))
        self.assertEqual(loaded["record"]["containment"], plan_graph.NESTED)

    def test_a_contract_that_contradicts_the_grammar_is_refused(self):
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "operators.json")
                            .read_text(encoding="utf-8"))
        record["execution_order"] = ["map", "filter", "fold", "reduce"]
        folder = Path(tempfile.mkdtemp()) / "operators.json"
        folder.write_text(json.dumps(record), encoding="utf-8")
        loaded = plan_graph.contract(folder)
        self.assertFalse(loaded["ok"])
        self.assertIn("execution_order", [problem["code"] for problem in loaded["problems"]])

    def test_the_prompt_is_rendered_from_the_declaration(self):
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "operators.json")
                            .read_text(encoding="utf-8"))
        text = plan_graph.render_contract_prompt(record)
        for phrase in ("Execution order: FILTER -> MAP -> FOLD -> REDUCE",
                       "Containment: FOLD contains ACCUMULATE",
                       "accumulate replaces fold",
                       'Authority must be "proposal"'):
            self.assertIn(phrase, text)
        # change the declaration, and the rendered prompt follows it
        record["forbid"] = ["invented rules"]
        self.assertIn("invented rules", plan_graph.render_contract_prompt(record))
        self.assertNotIn("extra operators", plan_graph.render_contract_prompt(record))


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = evaluation_harness.load()

    def test_both_conditions_share_one_system_prompt(self):
        report = contract_experiment.run(["stub"], self.corpus, repeats=1,
                                         complete_for={"stub": lambda prompt: reply(CONTRACTED)})
        self.assertEqual(report["system_prompt"], contract_experiment.system_prompt())
        self.assertTrue(report["system_prompt"])

    def test_the_baseline_has_no_contract_text(self):
        variants = contract_experiment.conditions()
        self.assertEqual(variants["baseline"]["suffix"], "")
        self.assertIn("Containment", variants["contract"]["suffix"])
        self.assertEqual(variants["contract"]["contract_uri"], "kuhul://operators/v1")

    def test_the_baseline_is_frozen_in_the_report(self):
        report = contract_experiment.run(["stub"], self.corpus, repeats=1,
                                         complete_for={"stub": lambda prompt: reply(CONTRACTED)})
        self.assertEqual(report["baseline_frozen"]["suffix"], contract_experiment.BASELINE_SUFFIX)
        self.assertIn("kept unchanged", report["baseline_frozen"]["note"])

    def test_repeats_measure_a_rate_not_a_single_run(self):
        calls = {"n": 0}

        def flaky(prompt):
            calls["n"] += 1
            return reply(CONTRACTED if calls["n"] % 2 else AMBIGUOUS)

        report = contract_experiment.run(["flaky"], self.corpus, repeats=4,
                                         complete_for={"flaky": flaky})
        baseline = report["results"]["flaky"]["baseline"]
        self.assertEqual(baseline["repeats"], 4)
        self.assertGreater(baseline["distinct_plans"], 1)
        self.assertIsNotNone(baseline["rate"])

    def test_only_exact_graph_equivalence_counts(self):
        def nearly(prompt):
            return reply(["filter", "map", "fold"])          # one operator missing

        report = contract_experiment.run(["nearly"], self.corpus, repeats=1,
                                         complete_for={"nearly": nearly})
        for cell in report["results"]["nearly"].values():
            self.assertEqual(cell["complete"], 0)
            self.assertEqual(cell["cells"][0]["verdict"], "missing_operators")

    def test_a_contract_following_model_passes_both_conditions(self):
        report = contract_experiment.run(["good"], self.corpus, repeats=2,
                                         complete_for={"good": lambda prompt: reply(CONTRACTED)})
        for cell in report["results"]["good"].values():
            self.assertEqual(cell["rate"], 1.0)

    def test_a_failed_call_is_a_failed_cell_not_a_crash(self):
        def explode(prompt):
            raise TimeoutError("too slow")

        report = contract_experiment.run(["slow"], self.corpus, repeats=2,
                                         complete_for={"slow": explode})
        for cell in report["results"]["slow"].values():
            self.assertEqual(cell["complete"], 0)
            self.assertIn("TimeoutError", cell["cells"][0]["error"])

    def test_the_report_does_not_claim_more_than_it_measured(self):
        report = contract_experiment.run(["stub"], self.corpus, repeats=1,
                                         complete_for={"stub": lambda prompt: reply(CONTRACTED)})
        self.assertEqual(report["case"], contract_experiment.CASE)
        self.assertIn("exact graph equivalence", report["note"])
        self.assertFalse(report["execution"])
        self.assertEqual(report["authority"], "declaration_only")


if __name__ == "__main__":
    unittest.main()
