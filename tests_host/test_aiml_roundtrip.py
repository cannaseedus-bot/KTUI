"""M25: AIML → GML → validated graph → match → SRAI → rendered output, compared with python-aiml.

This is the round trip the review asked for before migrating a corpus. It asserts three things:

  the migration keeps behaviour  - 16 inputs answer identically in python-aiml and through the graph
  the graph really validates    - the migrated set is assembled as the six contracts and checked by the
                                  package's own Bundle validator, not by a bespoke checker
  the four roles stay distinct  - category is a relationship object; pattern, template and srai are
                                  separate nodes; a redirect is an expression with guards, not an edge

Unsupported patterns (`<that>`, topics) are reported, never approximated.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aiml  # noqa: E402
import aiml_graph  # noqa: E402
import phases  # noqa: E402

BANKS = ("identity.aiml", "smalltalk.aiml", "memory.aiml", "gitops.aiml", "_override.aiml")
INPUTS = ("who are you", "what is your name", "hello", "hi", "hey", "how are you", "thanks",
          "bye", "good morning", "what changed", "git status", "build it", "commit this",
          "what is the time", "my dogs name is max", "what is my dogs name", "are you alice")


def migrate(banks=BANKS) -> list:
    categories = []
    for bank in banks:
        categories += aiml_graph.read_categories(ROOT / bank)
    return categories


def kernel_for(banks=BANKS):
    engine = aiml.Kernel()
    for bank in banks:
        engine.learn(str(ROOT / bank))
    return engine


class M25AimlRoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.categories = migrate()
        cls.kernel = kernel_for()

    # -- the migration -------------------------------------------------------------------------
    def test_every_category_migrates_with_provenance(self):
        self.assertEqual(len(self.categories), 131, "the five host banks hold 131 categories")
        self.assertTrue(all(not item.unsupported for item in self.categories))
        for item in self.categories:
            self.assertIn(":", item.category_id, "provenance is `bank:index`")
            self.assertTrue(item.pattern)

    def test_the_four_roles_stay_distinct_nodes(self):
        redirect = next(item for item in self.categories if item.pattern == "WHAT CHANGED")
        self.assertEqual(redirect.srai, "GIT STATUS")
        text = aiml_graph.to_gml(redirect)
        parsed = phases.core_module("gml2").parse(text)
        nodes = [entry.value for entry in parsed.entries if entry.name == "node"]
        kinds = [next(attribute.value for attribute in node.entries if attribute.name == "kind")
                 for node in nodes]
        self.assertEqual(sorted(kinds), ["category", "pattern", "srai", "template"])
        srai = next(node for node in nodes
                    if any(attribute.name == "kind" and attribute.value == "srai"
                           for attribute in node.entries))
        attributes = {attribute.name: attribute.value for attribute in srai.entries}
        self.assertEqual(attributes["expression"], "GIT STATUS")
        self.assertEqual(attributes["max_depth"], 3)
        self.assertEqual(attributes["visited_guard"], 1)

    def test_a_category_is_a_relationship_not_a_label(self):
        category = next(item for item in self.categories if item.pattern == "MY DOGS NAME IS *")
        parsed = phases.core_module("gml2").parse(aiml_graph.to_gml(category))
        node = next(entry.value for entry in parsed.entries
                    if entry.name == "node"
                    and any(attribute.name == "kind" and attribute.value == "category"
                            for attribute in entry.value.entries))
        attributes = {attribute.name: attribute.value for attribute in node.entries}
        self.assertTrue(attributes["pattern_ref"].startswith("aiml://pattern/"))
        self.assertTrue(attributes["template_ref"].startswith("aiml://template/"))
        self.assertEqual(attributes["category_id"], category.category_id)

    def test_template_segments_are_ordered_text_then_capture(self):
        category = next(item for item in self.categories if item.pattern == "MY DOGS NAME IS *")
        ordinals = [segment["ordinal"] for segment in category.segments]
        self.assertEqual(ordinals, list(range(len(category.segments))))
        kinds = [segment["kind"] for segment in category.segments]
        self.assertEqual(kinds, ["text", "capture"])
        self.assertEqual(category.segments[1]["index"], 1)

    # -- validation through the package --------------------------------------------------------
    def test_the_migrated_set_passes_the_package_validator(self):
        report = aiml_graph.validate(self.categories)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["state"], "BINDINGS_VALIDATED")
        self.assertEqual(report["migrated"], 131)

    def test_unsupported_patterns_are_reported_not_approximated(self):
        bank = Path(tempfile.mkdtemp()) / "context.aiml"
        bank.write_text(
            '<?xml version="1.0" encoding="UTF-8"?><aiml version="2.0">\n'
            '<category><pattern>HELLO</pattern><that>ASKED HELLO</that>'
            '<template>Again?</template></category>\n'
            '<category><pattern>PING</pattern><template>Pong</template></category>\n'
            '</aiml>\n', encoding="utf-8")
        migrated = aiml_graph.read_categories(bank)
        self.assertEqual(len(migrated), 2)
        self.assertEqual([item.unsupported for item in migrated], ["the/topic context", ""])
        report = aiml_graph.validate(migrated)
        self.assertIn("unsupported", [problem["code"] for problem in report["problems"]])
        self.assertEqual(report["migrated"], 1)

    # -- behaviour: match, srai, render --------------------------------------------------------
    def test_behaviour_matches_python_aiml(self):
        mismatches = []
        for text in INPUTS:
            expected = (self.kernel.respond(text) or "").strip()
            got = (aiml_graph.answer(self.categories, text).get("reply") or "").strip()
            if got != expected:
                mismatches.append((text, expected, got))
        self.assertEqual(mismatches, [], "the graph must answer exactly as the interpreter does")

    def test_captures_keep_the_users_case(self):
        self.assertEqual(aiml_graph.answer(self.categories, "my dogs name is Rex")["reply"],
                         "MEMORY remember pet.name Rex")
        self.assertEqual(aiml_graph.answer(self.categories, "my dogs name is max")["reply"],
                         "MEMORY remember pet.name max")

    def test_a_redirect_is_a_second_matching_pass(self):
        result = aiml_graph.answer(self.categories, "what changed")
        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"], "TOOL git status")
        self.assertEqual([hop["pattern"] for hop in result["trace"]],
                         ["WHAT CHANGED", "GIT STATUS"])
        self.assertEqual(len(result["trace"]), 2)

    def test_a_directive_stays_text_and_is_never_executed(self):
        result = aiml_graph.answer(self.categories, "git status")
        self.assertEqual(result["reply"], "TOOL git status",
                         "the graph renders the directive; the host decides whether to run it")

    # -- bounds --------------------------------------------------------------------------------
    def test_a_loop_terminates_with_a_bounded_failure(self):
        categories = [
            aiml_graph.Migrated(origin="test.aiml", index=0, pattern="PING", srai="PONG",
                                segments=[dict(ordinal=0, kind="redirect", value="PONG")]),
            aiml_graph.Migrated(origin="test.aiml", index=1, pattern="PONG", srai="PING",
                                segments=[dict(ordinal=0, kind="redirect", value="PING")]),
        ]
        result = aiml_graph.answer(categories, "ping")
        self.assertFalse(result["ok"])
        self.assertIn("loop", result["reason"])

    def test_depth_is_bounded(self):
        categories = [
            aiml_graph.Migrated(origin="t.aiml", index=index, pattern=f"STEP{index}",
                                srai=f"STEP{index + 1}",
                                segments=[dict(ordinal=0, kind="redirect",
                                               value=f"STEP{index + 1}")])
            for index in range(6)
        ]
        result = aiml_graph.answer(categories, "step0", max_depth=3)
        self.assertFalse(result["ok"])
        self.assertIn("max_depth", result["reason"])

    def test_a_pattern_with_two_wildcards_captures_both(self):
        captures = aiml_graph.match("WHAT IS * IN *", "what is water in french")
        self.assertEqual(captures, ["water", "french"])
        self.assertIsNone(aiml_graph.match("WHAT IS *", "hello there"))


if __name__ == "__main__":
    unittest.main()
