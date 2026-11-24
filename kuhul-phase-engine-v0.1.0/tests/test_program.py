"""K'UHUL program layer: the declared grammar parses, validates, serializes and traces.

The grammar from `grammar/kuhul-grammar.ebnf` is a *declaration* format, so the tests hold it to
declaration behaviour: vocabulary, arity, references and phase order are checked; nothing executes.

Two dialects ship in the package and both are covered:

    call style     glyph DATA = "…"   map(⟁DATA)   Pop { … }   lane risk : Graph { … }   bind A -> B
    bracket style  [Pop name]   [Yax resolve "x"]   [Sek FILTER "y"]   [Xul]      (graphs/*.khl)
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

import program  # noqa: E402

SAMPLE = """
# glyphs are declared by identifier and referenced with the glyph mark
glyph DATA = "enterprise:records"
relation RISK = "risk_shipping"

lane risk : Graph {
  map(⟁DATA)
  filter(⟁DATA)
  bind ⟁DATA -> risk
}

Pop { glyph phase_name = "enterprise_shipping_impact" }
Wo { sync(⟁DATA, ⟁RISK) }
Yax { dispatch(⟁RISK) }
Sek { fold(⟁DATA) reduce(⟁DATA) }
Chen { verify("provenance,units,coverage,permissions") }
Xul { emit("read_only_analysis_proposal") }
"""


class ProgramGrammarTests(unittest.TestCase):
    # -- lexer -----------------------------------------------------------------------------------
    def test_the_lexer_keeps_glyph_references_and_skips_comments(self):
        tokens = program.tokenize('# note\nglyph A = "v" map(⟁A) bind A -> B\n')
        kinds = [token.kind for token in tokens]
        self.assertEqual(kinds[:5], ["ident", "ident", "punct", "string", "ident"])
        glyph_values = [token.value for token in tokens if token.kind == "glyph"]
        self.assertEqual(glyph_values, ["⟁A"], "references keep the glyph mark")
        self.assertIn("glyph", [token.value for token in tokens if token.kind == "ident"])
        self.assertIn("arrow", kinds)

    def test_an_unexpected_character_is_an_error(self):
        with self.assertRaises(program.ProgramError):
            program.tokenize("map(⟁A) £")

    # -- parser ----------------------------------------------------------------------------------
    def test_every_construct_parses(self):
        parsed = program.parse(SAMPLE)
        kinds = {type(statement).__name__ for statement in parsed.statements}
        self.assertEqual(kinds, {"Declaration", "LaneBlock", "PhaseBlock"})
        self.assertEqual(parsed.glyphs(), {"DATA": "enterprise:records",
                                           "phase_name": "enterprise_shipping_impact"})
        self.assertEqual(parsed.relations(), {"RISK": "risk_shipping"})
        self.assertEqual(parsed.lanes(), {"risk": "Graph"})
        self.assertEqual(parsed.opcodes(),
                         ["map", "filter", "sync", "dispatch", "fold", "reduce", "verify", "emit"])

    def test_the_six_phases_are_recognised_and_canonicalised(self):
        parsed = program.parse(SAMPLE)
        self.assertEqual(parsed.phase_order(), ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])
        self.assertIn("Ch'en", parsed.phase_order(), "the grammar's Chen is Ch'en canonically")

    def test_a_glyph_declaration_must_use_an_identifier(self):
        with self.assertRaises(program.ProgramError):
            program.parse('glyph ⟁DATA = "x"')

    def test_an_unknown_phase_name_is_rejected(self):
        with self.assertRaisesRegex(program.ProgramError, "not a phase"):
            program.parse('Zap { emit("x") }')

    # -- validation ------------------------------------------------------------------------------
    def test_a_valid_program_validates(self):
        report = program.validate(program.parse(SAMPLE))
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["phases"], ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])

    def test_unknown_opcode_and_arity_are_reported(self):
        bad = program.parse('map(⟁A, 1, 2, 3, 4) frobnicate("x") glyph A = "v"')
        codes = {problem["code"] for problem in program.validate(bad)["problems"]}
        self.assertIn("unknown_opcode", codes)
        self.assertIn("arity", codes)

    def test_unresolved_glyph_and_reference_are_reported(self):
        bad = program.parse('map(⟁MISSING) emit(missing_lane)')
        codes = {problem["code"] for problem in program.validate(bad)["problems"]}
        self.assertIn("unresolved_glyph", codes)
        self.assertIn("unresolved_reference", codes)

    def test_unknown_lane_type_is_reported(self):
        bad = program.parse('lane risk : Imaginary { map(⟁A) } glyph A = "v"')
        self.assertIn("unknown_lane_type",
                      {problem["code"] for problem in program.validate(bad)["problems"]})

    def test_phases_are_used_as_needed(self):
        """A phase is meaningful only for the work it does: any subset, any order, is valid."""
        one = program.validate(program.parse('Wo { emit("x") }'))
        self.assertTrue(one["ok"], one["problems"])
        self.assertEqual(one["phases"], ["Wo"])
        self.assertEqual(one["order"], "subset")

        written = program.validate(program.parse('Xul { emit("x") } Pop { emit("y") }'))
        self.assertTrue(written["ok"], "the program's own order is not a defect")
        self.assertEqual(written["phases"], ["Xul", "Pop"])
        self.assertEqual(written["order"], "as-written")
        self.assertEqual(written["canonical"], ["Pop", "Xul"])

        all_six = program.validate(program.parse(
            'Pop { emit("a") } Wo { emit("b") } Yax { emit("c") } Sek { emit("d") } '
            'Chen { emit("e") } Xul { emit("f") }'))
        self.assertTrue(all_six["ok"])
        self.assertEqual(all_six["order"], "canonical")

    def test_strict_order_is_opt_in(self):
        parsed = program.parse('Xul { emit("x") } Pop { emit("y") }')
        self.assertTrue(program.validate(parsed)["ok"])
        strict = program.validate(parsed, strict_order=True)
        self.assertFalse(strict["ok"])
        self.assertIn("phase_order", {problem["code"] for problem in strict["problems"]})

    # -- serialization ---------------------------------------------------------------------------
    def test_serialization_is_round_trip_stable(self):
        parsed = program.parse(SAMPLE)
        once = program.serialize(parsed)
        twice = program.serialize(program.parse(once))
        self.assertEqual(once, twice)
        self.assertIn("lane risk : Graph {", once)
        self.assertIn("bind ⟁DATA -> risk", once)

    # -- the bracket dialect ---------------------------------------------------------------------
    def test_the_shipped_khl_example_parses_and_validates(self):
        parsed, dialect = program.load(ROOT / "graphs" / "shipping-impact.khl")
        self.assertEqual(dialect, "khl")
        report = program.validate(parsed, dialect=dialect)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["phases"], ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])
        self.assertIn("verify", report["opcodes"])
        self.assertIn("emit", report["opcodes"])

    # -- tracing, never execution ----------------------------------------------------------------
    def test_tracing_records_steps_and_defers_unbound_ones(self):
        trace = program.evaluate(program.parse(SAMPLE))
        self.assertFalse(trace["execution"])
        self.assertFalse(trace["mutation"])
        self.assertEqual(trace["authority"], "host")
        self.assertGreater(trace["deferred"], 0, "unbound opcodes must be reported, not faked")
        self.assertEqual([entry["phase"] for entry in trace["trace"] if entry["step"] == "verify"],
                         ["Ch'en"])

    def test_a_bound_step_runs_and_a_failing_step_is_reported(self):
        parsed = program.parse('Pop { map(⟁A) } glyph A = "v"')
        bound = program.evaluate(parsed, implementations={"map": lambda lanes, value: f"mapped:{value}"})
        self.assertEqual(bound["deferred"], 0)
        self.assertEqual(bound["trace"][1]["result"], "mapped:v")

        def explode(lanes, value):
            raise ValueError("no such lane")
        failed = program.evaluate(parsed, implementations={"map": explode})
        self.assertFalse(failed["ok"])
        self.assertIn("no such lane", failed["trace"][1]["error"])


if __name__ == "__main__":
    unittest.main()
