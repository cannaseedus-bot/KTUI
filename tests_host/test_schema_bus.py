"""M65: the schema URI bus - a valid message is not a permission, and versions move only through adapters.

The four refusals the review asked for, each with its own name:

    unknown_schema / payload_missing_field / authority_mismatch / version_mismatch   the message itself
    no_declared_edge                                                               routing
    capability_not_granted                                                          authorisation
    no_registered_adapter / missing_source_evidence                                 version evolution

And the learning pipeline: a `learning-delta` is a proposal, a `verified-delta` needs a PASS/FAIL verdict, and
neither is admitted by being produced.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import schema_bus  # noqa: E402

CANDIDATE = dict(schema_uri="urn:kuhul:schema:semantic-candidate:v1",
                 producer="micronaut://v1/grams",
                 payload=dict(source="black dog", target="large canine",
                              relation="semantic_similarity", score=0.87),
                 authority="proposal")


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = schema_bus.load()

    def test_the_registry_loads(self):
        self.assertTrue(self.registry["ok"], self.registry["problems"])
        self.assertEqual(len(self.registry["schemas"]), 8)
        self.assertEqual(len(self.registry["edges"]), 5)
        self.assertEqual(len(self.registry["adapters"]), 1)

    def test_every_schema_declares_a_class_and_required_fields(self):
        for uri, entry in self.registry["schemas"].items():
            self.assertIn(entry["authority"], schema_bus.AUTHORITY_CLASSES, uri)
            self.assertTrue(entry["required"], uri)
            self.assertTrue(uri.startswith("urn:kuhul:schema:"), uri)

    def test_an_edge_to_an_unknown_schema_is_refused(self):
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "schemas.json")
                            .read_text(encoding="utf-8"))
        record["edges"][0]["schema"] = "urn:kuhul:schema:ghost:v1"
        folder = Path(tempfile.mkdtemp()) / "schemas.json"
        folder.write_text(json.dumps(record), encoding="utf-8")
        report = schema_bus.load(folder)
        self.assertFalse(report["ok"])
        self.assertIn("edge", [problem["code"] for problem in report["problems"]])

    def test_an_unregistered_adapter_endpoint_is_refused(self):
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "schemas.json")
                            .read_text(encoding="utf-8"))
        record["adapters"][0]["emits"] = "urn:kuhul:schema:ghost:v2"
        folder = Path(tempfile.mkdtemp()) / "schemas.json"
        folder.write_text(json.dumps(record), encoding="utf-8")
        report = schema_bus.load(folder)
        self.assertFalse(report["ok"])
        self.assertIn("adapter", [problem["code"] for problem in report["problems"]])


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = schema_bus.load()

    def test_a_complete_message_validates(self):
        self.assertTrue(schema_bus.validate(self.registry, CANDIDATE)["ok"])

    def test_a_missing_required_field_is_named(self):
        broken = dict(CANDIDATE, payload=dict(source="a", target="b", relation="r"))
        result = schema_bus.validate(self.registry, broken)
        self.assertFalse(result["ok"])
        self.assertEqual(result["problems"][0]["code"], "payload_missing_field")
        self.assertIn("score", result["problems"][0]["detail"])

    def test_an_unknown_schema_is_refused(self):
        result = schema_bus.validate(self.registry, dict(CANDIDATE, schema_uri="urn:kuhul:schema:ghost:v1"))
        self.assertEqual(result["problems"][0]["code"], "unknown_schema")

    def test_an_authority_class_cannot_be_claimed(self):
        result = schema_bus.validate(self.registry, dict(CANDIDATE, authority="verified"))
        self.assertEqual(result["problems"][0]["code"], "authority_mismatch")

    def test_a_version_mismatch_is_refused(self):
        result = schema_bus.validate(self.registry, dict(CANDIDATE, version=2))
        self.assertIn("version_mismatch", [problem["code"] for problem in result["problems"]])


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = schema_bus.load()

    def test_a_declared_edge_with_the_capability_delivers(self):
        result = schema_bus.route(self.registry, CANDIDATE, consumer="micronaut://v1/relations",
                                  granted={"graph.relations.read"},
                                  authenticated_producer=CANDIDATE["producer"])
        self.assertTrue(result["delivered"])
        self.assertFalse(result["admitted"], "delivery is not admission")
        self.assertEqual(result["edges"][0]["to"], "micronaut://v1/relations")

    def test_a_matching_schema_without_an_edge_is_refused(self):
        result = schema_bus.route(self.registry, CANDIDATE, consumer="micronaut://v1/learning",
                                  granted={"graph.relations.read"},
                                  authenticated_producer=CANDIDATE["producer"])
        self.assertEqual(result["refused"], "no_declared_edge")

    def test_an_edge_without_the_capability_is_refused(self):
        result = schema_bus.route(self.registry, CANDIDATE, consumer="micronaut://v1/relations",
                                  granted=set(), authenticated_producer=CANDIDATE["producer"])
        self.assertEqual(result["refused"], "capability_not_granted")

    def test_a_spoofed_producer_finds_no_edge(self):
        spoofed = dict(CANDIDATE, producer="micronaut://v1/impostor")
        result = schema_bus.route(self.registry, spoofed, consumer="micronaut://v1/relations",
                                  granted={"graph.relations.read"},
                                  authenticated_producer="micronaut://v1/grams")
        # the host authenticated `grams`; the message claims `impostor`, so identity fails before edges
        self.assertEqual(result["refused"], "producer_not_authenticated")

    def test_consumers_are_listed_from_the_edges(self):
        consumers = schema_bus.consumers(self.registry, "urn:kuhul:schema:semantic-candidate:v1")
        self.assertEqual([edge["to"] for edge in consumers], ["micronaut://v1/relations"])


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = schema_bus.load()

    def test_a_registered_adapter_converts_when_the_payload_carries_the_new_field(self):
        v1 = dict(schema_uri="urn:kuhul:schema:relation:v1",
                  payload=dict(subject="Rex", predicate="is_a", object="dog", provenance="gml://x"))
        result = schema_bus.adapt(self.registry, v1, target="urn:kuhul:schema:relation:v2")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["schema_uri"], "urn:kuhul:schema:relation:v2")
        self.assertFalse(result["admitted"])

    def test_an_adapter_cannot_invent_the_field_it_adds(self):
        v1 = dict(schema_uri="urn:kuhul:schema:relation:v1",
                  payload=dict(subject="Rex", predicate="is_a", object="dog"))
        result = schema_bus.adapt(self.registry, v1, target="urn:kuhul:schema:relation:v2")
        self.assertFalse(result["ok"])
        self.assertEqual(result["refused"], "missing_source_evidence")

    def test_an_unregistered_conversion_is_refused(self):
        result = schema_bus.adapt(self.registry, CANDIDATE, target="urn:kuhul:schema:relation:v2")
        self.assertEqual(result["refused"], "no_registered_adapter")


class LearningTests(unittest.TestCase):
    def test_a_learning_delta_is_a_proposal(self):
        delta = schema_bus.learning_delta(dict(source="black dog", target="large canine",
                                               relation="semantic_similarity", score=0.87))
        self.assertEqual(delta["schema_uri"], "urn:kuhul:schema:learning-delta:v1")
        self.assertEqual(delta["authority"], "proposal")
        self.assertEqual(delta["requires"], "xcfe_admission")
        self.assertFalse(delta["persisted"])
        self.assertFalse(delta["admitted"])

    def test_a_verified_delta_needs_a_verdict(self):
        delta = schema_bus.learning_delta(dict(source="a", target="b", relation="r", score=0.5))
        for verdict in ("", "maybe", "UNKNOWN"):
            with self.assertRaises(ValueError):
                schema_bus.verified_delta(delta, verdict=verdict)
        verified = schema_bus.verified_delta(delta, verdict="FAIL", evidence="no source supports it")
        self.assertEqual(verified["authority"], "verified")
        self.assertFalse(verified["admitted"])

    def test_the_delta_validates_against_its_schema(self):
        registry = schema_bus.load()
        delta = schema_bus.learning_delta(dict(source="a", target="b", relation="r", score=0.5))
        self.assertTrue(schema_bus.validate(registry, delta)["ok"], delta)

    def test_a_learning_delta_routes_only_along_its_declared_edge(self):
        registry = schema_bus.load()
        delta = schema_bus.learning_delta(dict(source="a", target="b", relation="r", score=0.5))
        good = schema_bus.route(registry, delta, consumer="micronaut://v1/ch_en",
                                granted={"graph.relations.read"},
                                authenticated_producer=delta["producer"])
        bad = schema_bus.route(registry, delta, consumer="micronaut://v1/relations",
                               granted={"graph.relations.read"},
                               authenticated_producer=delta["producer"])
        self.assertTrue(good["delivered"])
        self.assertEqual(bad["refused"], "no_declared_edge")


class TypedPayloadTests(unittest.TestCase):
    """Presence, type and range are three different answers, and a bool is never a number."""

    @classmethod
    def setUpClass(cls):
        cls.registry = schema_bus.load()
        cls.uri = "urn:kuhul:schema:semantic-candidate:v1"

    def codes(self, payload) -> list[str]:
        return [problem["code"] for problem in
                schema_bus.validate_payload(self.registry, self.uri, payload)]

    def base(self, **overrides) -> dict:
        payload = dict(source="black dog", target="large canine", relation="semantic_similarity",
                       score=0.85)
        payload.update(overrides)
        return payload

    def test_a_valid_payload_has_no_problems(self):
        self.assertEqual(self.codes(self.base()), [])

    def test_a_string_score_is_a_type_mismatch(self):
        self.assertEqual(self.codes(self.base(score="high")), ["payload_type_mismatch"])

    def test_a_boolean_score_is_a_type_mismatch(self):
        self.assertEqual(self.codes(self.base(score=True)), ["payload_type_mismatch"],
                         "bool is a subclass of int in python, so it must be rejected explicitly")

    def test_a_missing_field_is_named(self):
        payload = self.base()
        del payload["score"]
        self.assertEqual(self.codes(payload), ["payload_missing_field"])

    def test_a_null_is_its_own_outcome(self):
        self.assertEqual(self.codes(self.base(score=None)), ["payload_null"])

    def test_a_value_outside_the_range_is_refused(self):
        self.assertEqual(self.codes(self.base(score=1.5)), ["payload_out_of_range"])
        self.assertEqual(self.codes(self.base(score=-0.1)), ["payload_out_of_range"])

    def test_an_enum_violation_is_refused(self):
        self.assertEqual(self.codes(self.base(relation="vibes")), ["payload_out_of_range"])

    def test_a_wrong_type_in_a_string_field_is_named(self):
        self.assertEqual(self.codes(self.base(source=42)), ["payload_type_mismatch"])

    def test_the_schema_declares_types_for_every_required_field(self):
        for uri, entry in self.registry["schemas"].items():
            declared = set((entry.get("types") or {}).keys())
            for field in entry.get("required") or []:
                self.assertIn(field, declared, f"{uri}: {field} has no declared type")


class ProducerIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = schema_bus.load()

    def test_the_host_identity_must_be_supplied(self):
        result = schema_bus.route(self.registry, CANDIDATE, consumer="micronaut://v1/relations",
                                  granted={"graph.relations.read"})
        self.assertEqual(result["refused"], "producer_not_authenticated")
        self.assertFalse(result["delivered"])

    def test_a_claimed_identity_that_disagrees_is_refused(self):
        result = schema_bus.route(self.registry, CANDIDATE, consumer="micronaut://v1/relations",
                                  granted={"graph.relations.read"},
                                  authenticated_producer="micronaut://v1/impostor")
        self.assertEqual(result["refused"], "producer_not_authenticated")

    def test_a_matching_identity_delivers_and_still_does_not_admit(self):
        result = schema_bus.route(self.registry, CANDIDATE, consumer="micronaut://v1/relations",
                                  granted={"graph.relations.read"},
                                  authenticated_producer=CANDIDATE["producer"])
        self.assertTrue(result["delivered"])
        self.assertFalse(result["admitted"])
        self.assertEqual(result["authenticated_producer"], CANDIDATE["producer"])


class LedgerBoundaryTests(unittest.TestCase):
    def test_the_record_says_verified_and_not_persisted(self):
        delta = schema_bus.learning_delta(dict(source="a", target="b", relation="semantic_similarity",
                                               score=0.5))
        verdict = schema_bus.verified_delta(delta, verdict="PASS", evidence="gml://x")
        record = schema_bus.ledger_record(delta, verdict, producer="micronaut://v1/ch_en",
                                          schema_version=1, verification="passed")
        self.assertFalse(record["admitted"])
        self.assertFalse(record["graph_mutated"])
        self.assertEqual(record["persistence"], "evidence_only")
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["verification"]["verdict"], "PASS")
        self.assertIn("not an admission", record["note"])

    def test_appending_writes_one_evidence_row(self):
        import tempfile

        import evidence_record

        folder = tempfile.TemporaryDirectory()
        original = evidence_record.LOG
        evidence_record.LOG = Path(folder.name) / "ledger.jsonl"
        try:
            delta = schema_bus.learning_delta(dict(source="a", target="b", relation="semantic_similarity",
                                                   score=0.5))
            verdict = schema_bus.verified_delta(delta, verdict="PASS", evidence="gml://x")
            result = schema_bus.append_verified_delta(delta, verdict,
                                                      producer="micronaut://v1/ch_en",
                                                      schema_version=1)
            rows = evidence_record.load()
            self.assertEqual(len(rows), 1)
            self.assertFalse(result["admitted"])
            self.assertFalse(result["record"]["graph_mutated"])
            self.assertEqual(sorted(result["evidence"]), ["hash", "sequence"],
                             "the append returns the ledger position and digest")
        finally:
            evidence_record.LOG = original
            folder.cleanup()


if __name__ == "__main__":
    unittest.main()
