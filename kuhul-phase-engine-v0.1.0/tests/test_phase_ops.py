"""M31: the 58 declared phase operations, classified - and the gated ones kept gated.

The six phase banks declare operations in their headers. That is vocabulary and intent, not runtime:
this audit says, for every declared operation, whether a capability exists, whether the host only has a
gated path, whether it can only be proposed, or whether nothing implements it yet.

The specific worry from review - `sek.aiml` declaring `execute_tool_chain`/`dispatch_call` and
`xul.aiml` declaring `gramWrite`/`persist_state`/`compare_and_commit` - is a guard, not a comment: a
gated operation that claims to be registered is a defect.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import phase_ops  # noqa: E402


class PhaseOpsAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = phase_ops.classify()

    # -- the inventory ----------------------------------------------------------------------------
    def test_the_six_banks_are_counted(self):
        found = phase_ops.inventory()
        self.assertEqual([bank["phase"] for bank in found["banks"]],
                         ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])
        self.assertEqual(found["categories"], 112)
        self.assertEqual(found["total_ops"], 58)
        self.assertEqual(found["unique_ops"], 58, "no operation is declared twice")
        per_bank = {bank["bank"]: bank["categories"] for bank in found["banks"]}
        self.assertEqual(per_bank, {"pop": 21, "wo": 14, "yax": 16, "sek": 23, "chen": 20, "xul": 18})

    def test_headers_carry_the_phase_metadata(self):
        found = phase_ops.inventory()
        first = found["banks"][0]
        self.assertEqual(first["phase"], "Pop")
        self.assertEqual(first["order"], 0)
        self.assertEqual(first["theta"], 0)
        self.assertEqual(first["verb"], "@read")
        self.assertFalse(first["terminal"])
        last = found["banks"][-1]
        self.assertTrue(last["terminal"], "Xul is the terminal phase")

    # -- classification ---------------------------------------------------------------------------
    def test_every_operation_is_classified_with_a_known_status(self):
        self.assertEqual(self.report["problems"], [])
        statuses = {row["status"] for row in self.report["rows"]}
        self.assertTrue(statuses <= set(phase_ops.STATUSES), statuses)
        self.assertEqual(len(self.report["rows"]), 58)
        self.assertEqual(sum(self.report["counts"].values()), 58)

    def test_registered_operations_resolve_to_a_callable(self):
        for row in self.report["rows"]:
            if row["status"] == "registered":
                self.assertTrue(row["callable"], f"{row['op']} -> {row['capability']}")

    def test_the_gated_operations_are_exactly_the_writes_and_executions(self):
        expected = {"execute_tool_chain", "dispatch_call", "compare_and_commit", "gramWrite",
                    "persist_state", "update_authorized_metric_parameters",
                    "invalidate_dependent_projections"}
        self.assertEqual(set(self.report["execute_gated"]), expected)
        sek = {row["op"] for row in self.report["rows"]
               if row["status"] == "requires_grant" and row["phase"] == "Sek"}
        xul = {row["op"] for row in self.report["rows"]
               if row["status"] == "requires_grant" and row["phase"] == "Xul"}
        self.assertEqual(sek, {"execute_tool_chain", "dispatch_call"})
        self.assertEqual(xul, {"compare_and_commit", "gramWrite", "persist_state",
                               "update_authorized_metric_parameters",
                               "invalidate_dependent_projections"})

    def test_a_gated_operation_may_never_be_registered(self):
        self.assertEqual(phase_ops.violations(), [])
        tampered = dict(phase_ops.BINDINGS)
        tampered["execute_tool_chain"] = ("registered", "compose.paragraph")
        self.assertEqual([item["detail"] for item in phase_ops.violations(tampered)],
                         ["execute_tool_chain"])

    def test_the_report_declares_that_matching_grants_nothing(self):
        self.assertEqual(self.report["authority"], "declaration_only")
        self.assertFalse(self.report["executes"])
        self.assertIn("grants nothing", self.report["note"])

    def test_unbound_operations_say_why(self):
        unbound = [row for row in self.report["rows"] if row["status"] == "unbound"]
        self.assertTrue(unbound)
        for row in unbound:
            self.assertTrue(row["reason"], row["op"])
        names = {row["op"] for row in unbound}
        self.assertIn("embedgemma_prompt_vectorize", names,
                      "there is no encoder in this repository, and the audit must say so")
        self.assertIn("graph_bfs", names, "the projection exists; the traversal does not")

    def test_the_report_is_deterministic(self):
        again = phase_ops.classify()
        self.assertEqual(json.dumps(self.report, sort_keys=True),
                         json.dumps(again, sort_keys=True))

    def test_the_summary_lists_every_status(self):
        text = phase_ops.summary(self.report)
        for word in ("registered", "requires_grant", "proposal_only", "unbound"):
            self.assertIn(word, text)
        self.assertIn("declaration_only", text)


if __name__ == "__main__":
    unittest.main()
