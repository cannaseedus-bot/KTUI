"""Typed GML Micronaut columns are addressable declarations, not dispatch authority."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gml2 import parse  # noqa: E402
import gml_columns  # noqa: E402
import gml_wiring  # noqa: E402
import operators  # noqa: E402


ROOT_URI = "micronaut://gml/relations"


def port(operator, column):
    return f"{ROOT_URI}/operators/{operator}/columns/{column}"


def edge(source, target, type_name, rank, shape, provenance):
    return dict(source_ref=source, target_ref=target, type=type_name, rank=rank,
                shape=shape, provenance=provenance)


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = gml_columns.load_catalog()

    def test_the_three_address_spaces_are_declared_separately(self):
        self.assertEqual(set(self.catalog["address_spaces"]), {"micronaut", "gml", "model"})
        self.assertEqual(gml_columns.resolve_address("gml://relations")["address_space"], "gml")
        self.assertEqual(gml_columns.resolve_address("model://qwen")["address_space"], "model")

    def test_every_operator_and_column_has_a_typed_uri(self):
        self.assertEqual(set(self.catalog["operators"]), set(gml_columns.REQUIRED_OPERATORS))
        for name, operator in self.catalog["operators"].items():
            self.assertEqual(gml_columns.resolve_column(operator["uri"])["kind"], "operator")
            for column in operator["columns"]:
                resolved = gml_columns.resolve_column(port(name, column))
                self.assertEqual(resolved["kind"], "column")
                self.assertEqual(resolved["operator"], name)

    def test_hylo_declares_unfold_fold_and_bounded_cycle_rules(self):
        recursion = self.catalog["operators"]["hylo"]["recursion"]
        self.assertEqual(recursion["unfold_operator"], "unfold")
        self.assertEqual(recursion["fold_operator"], "fold")
        self.assertEqual(recursion["cycle_policy"], "visited_set")
        self.assertGreater(recursion["max_depth"], 0)
        self.assertEqual(recursion["materialization"], "optional")


class EdgeTests(unittest.TestCase):
    def test_a_typed_edge_can_bind_unfold_to_map(self):
        result = gml_columns.validate_edge(edge(
            port("unfold", "branches"), port("map", "input"), "Lane<relation>", 1, ["N"],
            ["query", "expansion"]))
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["execution"])
        self.assertEqual(result["authority"], "declaration_only")

    def test_type_rank_shape_and_provenance_mismatches_are_refused(self):
        result = gml_columns.validate_edge(edge(
            port("map", "output"), port("filter", "input"), "Scalar", 0, [], ["transform"]))
        self.assertFalse(result["ok"])
        self.assertIn("source_type", [item["code"] for item in result["problems"]])
        self.assertIn("target_type", [item["code"] for item in result["problems"]])
        self.assertIn("source_rank", [item["code"] for item in result["problems"]])

    def test_graph_and_model_addresses_cannot_be_used_as_typed_ports(self):
        result = gml_columns.validate_edge(edge(
            "gml://relations", port("map", "input"), "Lane<relation>", 1, ["N"], ["expansion"]))
        self.assertFalse(result["ok"])
        self.assertIn("source", [item["code"] for item in result["problems"]])

    def test_the_gml_graph_validator_checks_edges_without_dispatch(self):
        doc = parse(f'''graph [
          schema "gml-wiring/1"
          graph_id "relations/chain"
          contract "typed_column_edges"
          authority "declaration_only"
          edge [ source_ref "{port("unfold", "branches")}" target_ref "{port("map", "input")}"
                 type "Lane<relation>" rank 1 shape [ dim "N" ]
                 provenance [ tag "query" tag "expansion" ] ]
        ]''')
        result = gml_wiring.validate(doc)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["state"], "BINDINGS_VALIDATED")
        self.assertFalse(result["execution"])

    def test_the_generic_uri_resolver_exposes_columns_without_granting(self):
        result = operators.resolve_uri(port("map", "output"))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["resolved"]["kind"], "column")
        self.assertEqual(result["resolved"]["direction"], "output")
        self.assertFalse(result["execution"])


if __name__ == "__main__":
    unittest.main()
