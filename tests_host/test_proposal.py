"""M36: operation proposals - the small prediction problem, validated by the host.

A model need not write a program; it can name six things:

    {"phase": "Sek", "operator": "filter", "target": "graph.matches",
     "binding": "valid", "next": "map", "authority": "proposal"}

The host checks the vocabulary, the shape, the reference, the binding, the chain and the authority claim
- and then still does not admit the work. A valid proposal converts to declarative K'UHUL source, which
the program layer validates again on its own terms.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import proposal  # noqa: E402


def pipeline():
    return [dict(phase="Sek", operator="filter", target="graph.matches", binding="valid",
                 next="map", authority="proposal"),
            dict(phase="Sek", operator="map", target="graph.matches", binding="transform",
                 next="fold", authority="proposal"),
            dict(phase="Sek", operator="fold", target="evidence", next="reduce",
                 authority="proposal"),
            dict(phase="Sek", operator="reduce", target="evidence", next=None, authority="proposal")]


class ProposalTests(unittest.TestCase):
    # -- the vocabulary ---------------------------------------------------------------------------
    def test_a_well_formed_proposal_validates(self):
        result = proposal.validate(pipeline()[0])
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["proposal"]["phase"], "Sek")
        self.assertEqual(result["proposal"]["operator"], "filter")

    def test_the_phase_may_be_spelled_like_the_banks(self):
        result = proposal.validate(dict(phase="chen", operator="reduce", target="evidence",
                                        authority="declaration_only"))
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["proposal"]["phase"], "Ch'en")

    def test_an_unknown_phase_or_operator_is_refused(self):
        unknown_phase = proposal.validate(dict(phase="Zap", operator="map", target="x",
                                               binding="y", authority="proposal"))
        self.assertIn("phase", [problem["code"] for problem in unknown_phase["problems"]])
        unknown_operator = proposal.validate(dict(phase="Sek", operator="explode", target="x",
                                                   authority="proposal"))
        self.assertIn("operator", [problem["code"] for problem in unknown_operator["problems"]])

    def test_a_target_must_be_a_registered_reference(self):
        for target in ("http://example.com/x", "", "a b", "-x"):
            result = proposal.validate(dict(phase="Sek", operator="fold", target=target,
                                            authority="proposal"))
            self.assertIn("target", [problem["code"] for problem in result["problems"]], target)
        for target in ("graph.matches", "gml://users/42", "kuhul://phases/sek", "⟁DATA"):
            result = proposal.validate(dict(phase="Sek", operator="fold", target=target,
                                            authority="proposal"))
            self.assertTrue(result["ok"], (target, result["problems"]))

    def test_filter_and_map_require_a_binding(self):
        result = proposal.validate(dict(phase="Sek", operator="filter", target="graph.matches",
                                        authority="proposal"))
        self.assertIn("binding", [problem["code"] for problem in result["problems"]])

    # -- authority --------------------------------------------------------------------------------
    def test_an_authority_claim_other_than_proposal_is_refused(self):
        for authority in ("execute", "granted", "", "admin"):
            result = proposal.validate(dict(phase="Sek", operator="fold", target="evidence",
                                            authority=authority))
            self.assertIn("authority", [problem["code"] for problem in result["problems"]], authority)

    def test_a_valid_proposal_is_still_not_admitted(self):
        result = proposal.validate(pipeline()[0])
        self.assertTrue(result["ok"])
        self.assertFalse(result["admitted"])
        self.assertFalse(result["execution"])
        self.assertEqual(result["authority"], "declaration_only")

    # -- the chain --------------------------------------------------------------------------------
    def test_the_operator_chain_is_followed(self):
        report = proposal.validate_all(pipeline())
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual([result["proposal"]["operator"] for result in report["results"]],
                         ["filter", "map", "fold", "reduce"])

    def test_a_broken_chain_is_reported(self):
        broken = pipeline()
        broken[0]["next"] = "reduce"
        report = proposal.validate_all(broken)
        self.assertFalse(report["ok"])
        self.assertIn("chain_mismatch", [problem["code"] for problem in report["problems"]])

    def test_next_may_name_a_phase_instead_of_an_operator(self):
        steps = [dict(phase="Sek", operator="reduce", target="evidence", next="Ch'en",
                      authority="proposal"),
                 dict(phase="Ch'en", operator="filter", target="graph.matches", binding="verified",
                      next=None, authority="proposal")]
        report = proposal.validate_all(steps)
        self.assertTrue(report["ok"], report["problems"])

    def test_an_unusual_phase_is_a_notice_not_a_refusal(self):
        result = proposal.validate(dict(phase="Pop", operator="fold", target="evidence",
                                        authority="proposal"))
        self.assertTrue(result["ok"], "a phase may use an operator for its own purposes")
        self.assertIn("unusual_phase", [notice["code"] for notice in result["notices"]])

    # -- the conversion ---------------------------------------------------------------------------
    def test_accepted_proposals_become_declarative_source(self):
        report = proposal.plan(pipeline())
        self.assertTrue(report["ok"], report["proposals"]["problems"])
        self.assertIn("Sek {", report["source"])
        self.assertIn('filter("graph.matches", "valid")', report["source"])
        self.assertTrue(report["program"]["ok"], report["program"])
        self.assertEqual(report["program"]["phases"], ["Sek"])

    def test_a_rejected_set_produces_no_source(self):
        report = proposal.plan([dict(phase="Sek", operator="filter", target="graph.matches",
                                     authority="proposal")])
        self.assertFalse(report["ok"])
        self.assertEqual(report["source"], "")

    def test_the_plan_never_admits(self):
        report = proposal.plan(pipeline())
        self.assertFalse(report["admitted"])
        self.assertFalse(report["execution"])
        self.assertFalse(report["mutation"])
        self.assertEqual(report["authority"], "declaration_only")
        self.assertIn("admitted: false", proposal.summary(report))


if __name__ == "__main__":
    unittest.main()
