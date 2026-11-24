"""M24: the five GML/2 contract issues, checked against the real package.

The review's five points, each as a guard:

1. **References.** Local edges use integers; external ones use `source_ref`/`target_ref` with an
   explicit resolver mode. A bare `pattern:1` is not a reference, a `gml://` whole-graph reference is
   not a node reference, and a foreign schema is not accepted.
2. **SRAI is dynamic.** A redirect expression with `{star:N}` may not use a static `@redirects_to`
   edge; it declares `max_depth` and `visited_guard` instead.
3. **The cycle guard is runtime.** The static validator only checks that the safeguards are declared;
   `srai_resolver` enforces depth and a visited set keyed on the resolved expression plus captures.
4. **Capability states are separate.** A portable graph whose capability this host lacks stops at
   STRUCTURALLY_VALIDATED with the missing capability named - only a broken document is REJECTED.
5. **Templates are ordered.** `segment [ ordinal ... ]` preserves text/substitution order; the
   `spans`/`slots` form cannot express it and fails the capture bounds check.

Plus the parser/serializer property the review asks for first: canonical, deterministic, round-trip
stable.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aiml_host  # noqa: E402
import phases  # noqa: E402
import srai_resolver  # noqa: E402

CORE = phases.ROOT / "core"
CONTRACTS = phases.ROOT / "aiml_contracts"


def modules():
    return dict(gml2=phases.core_module("gml2"), resolvers=phases.core_module("resolvers"),
                rules=phases.core_module("rules"), bundle=phases.core_module("aiml_bundle"),
                extension=phases.core_module("extension"))


def documents():
    """The six contracts, parsed, keyed the way the bundle expects."""
    gml2 = modules()["gml2"]
    return {f"{path.stem}/main": gml2.parse(path.read_text(encoding="utf-8"))
            for path in sorted(CONTRACTS.glob("*.gml"))}


def copy_contracts(folder: Path) -> Path:
    target = folder / "contracts"
    shutil.copytree(CONTRACTS, target)
    return target


def node_block(text: str):
    """Parse a single `node [ ... ]` into the node's own block (gml2 requires a graph root)."""
    gml2 = phases.core_module("gml2")
    document = gml2.parse(f"graph [ {text} ]")
    return document.entries[0].value


class M24Gml2Contracts(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    # -- 0. parser and canonical serializer ------------------------------------------------------
    def test_parse_and_serialize_round_trip_is_stable(self):
        gml2 = modules()["gml2"]
        for path in sorted(CONTRACTS.glob("*.gml")):
            text = path.read_text(encoding="utf-8")
            once = gml2.serialize(gml2.parse(text))
            twice = gml2.serialize(gml2.parse(once))
            self.assertEqual(once, twice, f"{path.name} is not round-trip stable")
            self.assertEqual(gml2.parse(once), gml2.parse(twice), path.name)

    # -- 1. reference modes ----------------------------------------------------------------------
    def test_a_bare_colon_target_is_not_a_reference(self):
        resolvers = modules()["resolvers"]
        with self.assertRaises(resolvers.ResolutionError) as caught:
            resolvers.resolve("pattern:1", documents(), expected="node_addressable")
        self.assertIn("invalid reference", str(caught.exception))

    def test_whole_graph_and_node_references_are_distinct_modes(self):
        resolvers = modules()["resolvers"]
        docs = documents()
        self.assertIsNotNone(resolvers.resolve("aiml://pattern/main#1", docs,
                                              expected="node_addressable",
                                              expected_schema="aiml-gml/1"))
        with self.assertRaisesRegex(resolvers.ResolutionError, "mode mismatch"):
            resolvers.resolve("gml://pattern/main", docs, expected="node_addressable")

    def test_a_foreign_schema_reference_is_refused(self):
        resolvers = modules()["resolvers"]
        with self.assertRaisesRegex(resolvers.ResolutionError, "schema mismatch"):
            resolvers.resolve("aiml://pattern/main#1", documents(), expected="node_addressable",
                              expected_schema="gml-tensor/1")

    def test_mixed_endpoint_modes_are_refused(self):
        rules, gml2 = modules()["rules"], modules()["gml2"]
        folder = copy_contracts(self.root)
        mixed = folder / "category.gml"
        mixed.write_text('graph [ schema "aiml-gml/1" graph_id "category/main" contract "category" '
                         'node [ id 3 kind "category" pattern_ref "aiml://pattern/main#1" '
                         'template_ref "aiml://template/main#2" ] '
                         'edge [ source 3 target_ref "aiml://template/main#2" verb "@uses" ] ]',
                         encoding="utf-8")
        bundle = modules()["bundle"].Bundle(
            {f"{path.stem}/main": gml2.parse(path.read_text(encoding="utf-8"))
             for path in sorted(folder.glob("*.gml"))},
            modules()["extension"].load_extension(modules()["gml2"].parse(
                (phases.ROOT / "schemas" / "aiml-registry.gml").read_text(encoding="utf-8"))))
        with self.assertRaisesRegex(Exception, "mixed or incomplete edge endpoint mode"):
            bundle.validate()

    # -- 2. SRAI is a dynamic redirect -----------------------------------------------------------
    def test_a_dynamic_redirect_may_not_use_a_static_edge(self):
        rules, gml2 = modules()["rules"], modules()["gml2"]
        node = node_block('node [ id 7 kind "srai" expression "WHAT IS {star:1}" '
                          'max_depth 3 visited_guard 1 ]')
        with self.assertRaisesRegex(Exception, "dynamic SRAI cannot use static"):
            rules.srai_static_ok(node=node)

    def test_a_redirect_must_declare_its_safeguards(self):
        rules, gml2 = modules()["rules"], modules()["gml2"]
        unguarded = node_block('node [ id 7 kind "srai" expression "WHAT IS {star:1}" ]')
        with self.assertRaisesRegex(Exception, "positive max_depth and visited_guard 1"):
            rules.srai_guards_present(node=unguarded)
        guarded = node_block('node [ id 7 kind "srai" expression "WHAT IS {star:1}" '
                             'max_depth 3 visited_guard 1 ]')
        self.assertIsNone(rules.srai_guards_present(node=guarded))

    # -- 3. the cycle guard is a runtime property ------------------------------------------------
    def test_a_substituted_loop_is_caught_at_runtime(self):
        table = {"A": "SRAI B", "B": "SRAI A"}
        with self.assertRaisesRegex(srai_resolver.SraiCycle, "loop detected"):
            srai_resolver.resolve("A", [], lambda text: table.get(text, ""))

    def test_depth_and_visited_guard_are_both_enforced(self):
        with self.assertRaisesRegex(srai_resolver.SraiCycle, "max_depth"):
            srai_resolver.resolve("A", [], lambda text: f"SRAI {text}Z", max_depth=2)
        with self.assertRaisesRegex(srai_resolver.SraiCycle, "visited_guard"):
            srai_resolver.resolve("A", [], lambda text: "done", visited_guard=0)

    def test_a_clean_chain_resolves_and_reports_its_trace(self):
        table = {"WHAT IS SATURN": "A planet."}
        outcome = srai_resolver.resolve("WHAT IS {star:1}", ["SATURN"], lambda text: table.get(text, ""))
        self.assertEqual(outcome["reply"], "A planet.")
        self.assertEqual(outcome["depth"], 0)
        self.assertEqual(outcome["trace"][0]["resolved"], "WHAT IS SATURN")

    # -- 4. capability states --------------------------------------------------------------------
    def test_a_missing_capability_stops_at_bindings_not_rejected(self):
        folder = copy_contracts(self.root)
        category = folder / "category.gml"
        category.write_text(
            'graph [ schema "aiml-gml/1" graph_id "category/main" contract "category" '
            'node [ id 3 kind "category" pattern_ref "aiml://pattern/main#1" '
            'template_ref "aiml://template/main#2" '
            'requires [ capability "pattern_index.lookup" signature "string -> pattern_candidates" ] ] ]',
            encoding="utf-8")
        report = aiml_host.states(folder=folder, host_capabilities=())
        self.assertEqual(report["state"], "STRUCTURALLY_VALIDATED")
        self.assertTrue(report["portable"], "a portable graph must not be called invalid")
        self.assertEqual(report["missing_capabilities"], ["pattern_index.lookup"])
        resolved = aiml_host.states(folder=folder, host_capabilities=("pattern_index.lookup",))
        self.assertEqual(resolved["state"], "BINDINGS_VALIDATED")
        self.assertEqual(resolved["missing_capabilities"], [])

    def test_a_broken_document_is_rejected_and_names_the_stage(self):
        folder = copy_contracts(self.root)
        (folder / "pattern.gml").write_text(
            'graph [ schema "aiml-gml/1" graph_id "pattern/main" contract "pattern" '
            'node [ id 1 kind "pattern" expression "WHO IS *" wildcard_count 2 ] ]', encoding="utf-8")
        report = aiml_host.states(folder=folder)
        self.assertEqual(report["state"], "REJECTED")
        self.assertEqual(report["stage"], "rules")
        self.assertFalse(report["portable"])

    def test_the_host_never_claims_executable_or_admitted(self):
        report = aiml_host.states()
        states = [reason["code"] for reason in report["reasons"]]
        self.assertIn("executable", states)
        self.assertIn("admitted", states)
        self.assertEqual(report["state"], "BINDINGS_VALIDATED")

    # -- 5. ordered templates --------------------------------------------------------------------
    def test_template_segments_keep_text_and_substitution_order(self):
        gml2 = modules()["gml2"]
        node = [entry.value for entry in documents()["template/main"].entries
                if entry.name == "node"][0]
        segments = [(int(attribute.value)
                     for attribute in segment.value.entries if attribute.name == "ordinal")
                    for segment in node.entries if segment.name == "segment"]
        ordinals = [next(iter(values)) for values in segments]
        self.assertEqual(ordinals, sorted(ordinals), "segments must be ordered by ordinal")
        kinds = [next(attribute.value for attribute in segment.value.entries
                      if attribute.name == "kind")
                 for segment in node.entries if segment.name == "segment"]
        self.assertEqual(kinds[:2], ["text", "capture"])

    def test_spans_and_slots_cannot_express_the_order(self):
        rules, gml2 = modules()["rules"], modules()["gml2"]
        spans_form = node_block('node [ id 2 kind "template" output_type "redirect" '
                                'spans [ value "WHAT IS " ] slots [ value "star:1" ] ]')
        with self.assertRaisesRegex(Exception, "no ordered segments"):
            rules.template_ordinals_contiguous(node=spans_form)


if __name__ == "__main__":
    unittest.main()
