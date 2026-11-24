"""M85: the runtime does not depend on the cryptographic evaluation layer.

The security story got confusing because three concerns were being discussed as one: correctness, controlled
execution, and scientific evidence about evidence. This guard states the division in code - the runtime modules
must not import the optional evaluation facility, so deleting that facility leaves a working bot.
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RUNTIME = (
    "chat_app.py", "phase_routing.py", "binding_resolver.py", "schema_bus.py",
    "learning_pipeline.py", "runtime_tree.py", "model_lifecycle.py", "inference_session.py",
    "profile.py", "grams.py", "corpus.py", "model_router.py",
)
OPTIONAL = {
    "review_attestations", "keymaker", "evidence_gate", "evaluation_harness",
    "rescore", "review_packet", "ce_protocol", "ce_experiment", "bound_scoring",
}


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


class RuntimeIndependenceTests(unittest.TestCase):
    def test_no_runtime_module_imports_the_evaluation_facility(self):
        offenders = {}
        for name in RUNTIME:
            path = ROOT / name
            if not path.is_file():
                continue
            overlap = imports_of(path) & OPTIONAL
            if overlap:
                offenders[name] = sorted(overlap)
        self.assertEqual(offenders, {},
                         "the runtime must not depend on the optional evaluation facility")

    def test_the_optional_layer_is_where_it_is_named(self):
        for name in ("review_attestations.py", "keymaker.py", "evidence_gate.py",
                     "evaluation_harness.py"):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_the_runtime_still_imports_with_the_facility_blocked(self):
        import importlib

        blocked = sorted(OPTIONAL)
        saved = {name: sys.modules.pop(name, None) for name in blocked}
        try:
            for module in ("schema_bus", "binding_resolver", "profile", "grams", "phase_routing"):
                sys.modules.pop(module, None)
                imported = importlib.import_module(module)
                self.assertIsNotNone(imported)
        finally:
            for name, module in saved.items():
                if module is not None:
                    sys.modules[name] = module

    def test_schema_validation_is_required_and_stays(self):
        # correctness is not optional: the typed checks live in the runtime layer
        import schema_bus

        registry = schema_bus.load()
        problems = schema_bus.validate_payload(registry, "urn:kuhul:schema:semantic-candidate:v1",
                                                dict(source="a", target="b",
                                                     relation="semantic_similarity", score=True))
        self.assertEqual([problem["code"] for problem in problems], ["payload_type_mismatch"])

    def test_control_flow_separation_is_required_and_stays(self):
        # a delivered message is never an admitted operation
        import schema_bus

        registry = schema_bus.load()
        message = dict(schema_uri="urn:kuhul:schema:semantic-candidate:v1",
                       producer="micronaut://v1/grams",
                       payload=dict(source="a", target="b", relation="semantic_similarity", score=0.5),
                       authority="proposal")
        routed = schema_bus.route(registry, message, consumer="micronaut://v1/relations",
                                  granted={"graph.relations.read"},
                                  authenticated_producer="micronaut://v1/grams")
        self.assertTrue(routed["delivered"])
        self.assertFalse(routed["admitted"], "delivery is not admission, with or without an attacker")

    def test_the_security_notes_describe_this_exact_division(self):
        text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("optional facility", text)
        self.assertIn("Data does not become an instruction", text)
        self.assertIn("out of scope for this", text)


if __name__ == "__main__":
    unittest.main()
