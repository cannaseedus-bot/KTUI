"""Command strings are typed candidates; none of them is execution authority."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import command_addresses  # noqa: E402
import operators  # noqa: E402


class CommandAddressTests(unittest.TestCase):
    def test_all_command_families_parse_as_candidates(self):
        uris = (
            "srai://relations/query",
            "delta://learning/propose",
            "tool://gramstore/search",
            "verb://graph/filter",
            "micronaut://gml/relations",
            "model://planner",
        )
        for uri in uris:
            with self.subTest(uri=uri):
                result = command_addresses.resolve(uri)
                self.assertEqual(result["schema"], command_addresses.SCHEMA)
                self.assertTrue(result["command_candidate"])
                self.assertFalse(result["admitted"])
                self.assertFalse(result["execution"])

    def test_verb_resolves_to_the_typed_gml_operator(self):
        result = command_addresses.resolve("verb://graph/filter")
        self.assertTrue(result["route_declared"])
        self.assertEqual(result["target"]["kind"], "operator")
        self.assertEqual(result["target"]["operator"], "filter")

    def test_verb_column_resolves_to_a_typed_port(self):
        result = command_addresses.resolve("verb://graph/map/columns/output")
        self.assertEqual(result["target"]["kind"], "column")
        self.assertEqual(result["target"]["direction"], "output")
        self.assertEqual(result["target"]["type"], "Lane<U>")

    def test_delta_is_proposal_only(self):
        result = command_addresses.resolve("delta://learning/propose")
        self.assertEqual(result["result"], "typed_delta_proposal")
        self.assertFalse(result["mutation"])
        self.assertFalse(result["persistence"])

    def test_model_candidate_does_not_select_or_execute_a_model(self):
        result = command_addresses.resolve("model://planner")
        self.assertFalse(result["route_declared"])
        self.assertFalse(result["execution"])
        self.assertTrue(command_addresses.validate_candidate(result)["ok"])

    def test_existing_uri_walker_uses_the_same_command_resolver(self):
        result = operators.resolve_uri("tool://gramstore/search")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["resolved"]["family"], "tool")
        self.assertFalse(result["execution"])

    def test_unknown_family_is_refused(self):
        with self.assertRaises(command_addresses.CommandAddressError):
            command_addresses.resolve("exec://shell/run")


if __name__ == "__main__":
    unittest.main()
