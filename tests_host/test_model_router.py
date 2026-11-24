"""M42: the model router - a binding, not an invocation, and only after the corpus declines.

Two rules under test:

**Only registered endpoints are probed.** An unregistered name is refused without a request; a registered
one whose `/models` probe fails is rejected with the reason. Nothing scans ports.

**AIML answers first.** `plan_invocation()` asks the phase chain; when the chain handles the turn, no model
is proposed at all.
"""
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import model_router  # noqa: E402

READ = {"graph.relations.read"}


class FakeModelServer:
    """A registered-shaped endpoint that answers /v1/models - the router's only probe."""

    def __init__(self, models=("fake-tiny",), status=200):
        payload = json.dumps({"data": [{"id": name} for name in models]}).encode("utf-8")
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.rstrip("/").endswith("/models"):
                    self.send_response(outer.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, *args):
                return

        self.status = status
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}/v1"
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def router_with(base_url: str, *, authority="declaration_only") -> dict:
    record = {"schema": "kuhul-model-router/v1", "authority": authority,
              "models": {"worker": {"base_url": base_url, "role": "fast_inference",
                                    "preference": "fast", "features": ["chat"]},
                         "advisor": {"base_url": base_url, "role": "complex_reasoning",
                                     "preference": "deep", "features": ["chat", "tools"]}},
              "routing": {"micronaut://v1/aiml": "worker",
                          "micronaut://v1/compose": "advisor"},
              "preferences": {"fast": ["worker", "advisor"], "deep": ["advisor", "worker"]},
              "policy": {"probe": "/models", "timeout_seconds": 2, "require_registered": True}}
    folder = Path(tempfile.mkdtemp()) / "models.json"
    folder.write_text(json.dumps(record), encoding="utf-8")
    return model_router.load(folder)


class ManifestTests(unittest.TestCase):
    def test_the_shipped_router_is_valid(self):
        router = model_router.load()
        self.assertTrue(router["ok"], router["problems"])
        self.assertEqual(router["authority"], "declaration_only")
        self.assertEqual(sorted(router["models"]), ["advisor", "planner", "worker"])
        self.assertEqual(len(router["routing"]), 5)

    def test_a_non_loopback_endpoint_is_refused(self):
        with FakeModelServer() as fake:
            router = router_with(fake.base_url)
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "models.json")
                            .read_text(encoding="utf-8"))
        record["models"]["worker"]["base_url"] = "http://10.0.0.5:9040/v1"
        path = Path(tempfile.mkdtemp()) / "models.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        report = model_router.load(path)
        self.assertFalse(report["ok"])
        self.assertIn("base_url", [problem["code"] for problem in report["problems"]])

    def test_registration_cannot_be_optional(self):
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "models.json")
                            .read_text(encoding="utf-8"))
        record["policy"]["require_registered"] = False
        path = Path(tempfile.mkdtemp()) / "models.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        report = model_router.load(path)
        self.assertFalse(report["ok"])
        self.assertIn("policy", [problem["code"] for problem in report["problems"]])

    def test_a_routing_target_must_be_a_registered_model(self):
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "models.json")
                            .read_text(encoding="utf-8"))
        record["routing"]["micronaut://v1/aiml"] = "ghost"
        path = Path(tempfile.mkdtemp()) / "models.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        report = model_router.load(path)
        self.assertFalse(report["ok"])
        self.assertIn("routing", [problem["code"] for problem in report["problems"]])


class HealthTests(unittest.TestCase):
    def test_a_registered_endpoint_is_probed(self):
        with FakeModelServer(models=("fake-tiny",)) as fake:
            router = router_with(fake.base_url)
            result = model_router.health(router, "worker")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["models"], ["fake-tiny"])
        self.assertLess(result["latency_ms"], 5000)

    def test_an_unregistered_name_is_never_contacted(self):
        with FakeModelServer() as fake:
            router = router_with(fake.base_url)
            result = model_router.health(router, "ghost")
        self.assertFalse(result["ok"])
        self.assertEqual(result["refused"], "model_not_registered")
        self.assertNotIn("url", result, "no request is made for an unregistered model")

    def test_an_unreachable_endpoint_is_reported(self):
        # A registered endpoint that is not listening: point at a closed loopback port so the test does
        # not depend on whether a second server happens to be running in this checkout.
        router = router_with("http://127.0.0.1:9/v1")
        result = model_router.health(router, "worker")
        self.assertFalse(result["ok"])
        self.assertEqual(result["refused"], "unreachable")
        self.assertIn("latency_ms", result)

    def test_a_non_model_response_is_not_health(self):
        with FakeModelServer(models=()) as fake:
            router = router_with(fake.base_url)
            result = model_router.health(router, "worker")
        self.assertFalse(result["ok"])
        self.assertEqual(result["refused"], "no_models_listed")


class ShippedRoutingTests(unittest.TestCase):
    """The shipped manifest: conversation on gemma, structured planning on qwen, analysis on gpt-oss."""

    @classmethod
    def setUpClass(cls):
        cls.router = model_router.load()
        cls.probes = {name: {"ok": True, "models": [name]} for name in cls.router["models"]}

    def test_structured_micronauts_route_to_the_planner(self):
        for micronaut in ("micronaut://v1/relations", "micronaut://v1/compose"):
            binding = model_router.select(self.router, micronaut, probes=self.probes)
            self.assertEqual(binding["selected"], "planner", micronaut)

    def test_conversational_micronauts_stay_on_the_worker(self):
        for micronaut in ("micronaut://v1/aiml", "micronaut://v1/eliza"):
            binding = model_router.select(self.router, micronaut, probes=self.probes)
            self.assertEqual(binding["selected"], "worker", micronaut)

    def test_the_plan_preference_falls_back_in_order(self):
        binding = model_router.select(self.router, "micronaut://v1/compose", preference="plan",
                                      probes={"planner": {"ok": False, "refused": "unreachable"},
                                              "advisor": {"ok": True}, "worker": {"ok": True}})
        self.assertEqual(binding["selected"], "advisor")


class SelectionTests(unittest.TestCase):
    def test_the_declared_model_wins(self):
        with FakeModelServer() as fake:
            router = router_with(fake.base_url)
            binding = model_router.select(router, "micronaut://v1/aiml")
        self.assertTrue(binding["ok"], binding)
        self.assertEqual(binding["selected"], "worker")
        self.assertFalse(binding["admitted"])
        self.assertEqual(binding["authority"], "declaration_only")

    def test_preference_order_is_followed_when_the_first_choice_is_down(self):
        with FakeModelServer() as fake:
            router = router_with(fake.base_url)
            probes = {"worker": {"ok": False, "refused": "unreachable"},
                      "advisor": model_router.health(router, "advisor")}
            binding = model_router.select(router, "micronaut://v1/aiml", probes=probes)
        self.assertEqual(binding["selected"], "advisor")
        self.assertEqual(binding["rejected"][0]["model"], "worker")

    def test_required_features_filter_the_choice(self):
        with FakeModelServer() as fake:
            router = router_with(fake.base_url)
            binding = model_router.select(router, "micronaut://v1/aiml", features=("tools",))
        self.assertEqual(binding["selected"], "advisor", "worker declares only chat")
        self.assertIn("missing_features", [item["reason"] for item in binding["rejected"]])

    def test_an_unrouted_micronaut_is_refused(self):
        router = model_router.load()
        binding = model_router.select(router, "micronaut://v1/unknown")
        self.assertFalse(binding["ok"])
        self.assertEqual(binding["refused"], "micronaut_not_routed")

    def test_nothing_healthy_is_refused_with_reasons(self):
        with FakeModelServer() as fake:
            router = router_with(fake.base_url)
            binding = model_router.select(router, "micronaut://v1/aiml",
                                          probes={"worker": {"ok": False, "refused": "unreachable"},
                                                  "advisor": {"ok": False, "refused": "unreachable"}})
        self.assertFalse(binding["ok"])
        self.assertEqual(binding["refused"], "no_healthy_endpoint")
        self.assertEqual(len(binding["rejected"]), 2)

    def test_selection_is_deterministic(self):
        with FakeModelServer() as fake:
            router = router_with(fake.base_url)
            first = json.dumps(model_router.select(router, "micronaut://v1/aiml"), sort_keys=True)
            second = json.dumps(model_router.select(router, "micronaut://v1/aiml"), sort_keys=True)
        self.assertEqual(first, second)


class InvocationTests(unittest.TestCase):
    def test_the_corpus_answers_first_and_no_model_is_proposed(self):
        with FakeModelServer() as fake:
            router = router_with(fake.base_url)
            plan = model_router.plan_invocation(router, "tell me about my dog", granted=READ)
        self.assertFalse(plan["invoke_model"])
        self.assertEqual(plan["routing_action"], "chain")
        self.assertIn("no tokens spent", plan["reason"])

    def test_a_refused_turn_cannot_be_overridden_by_a_model(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "pop.json").write_text(json.dumps({
            "schema": "kuhul-phases/v1", "phase": "Pop", "uri": "kuhul://phases/pop",
            "aiml": [], "next": "kuhul://phases/xul", "authority": "declaration_only",
            "bindings": [{"pattern": "COMMIT THE TREE", "directive": "GITOP commit",
                          "capability": "repo.write"}]}), encoding="utf-8")
        (folder / "xul.json").write_text(json.dumps({
            "schema": "kuhul-phases/v1", "phase": "Xul", "uri": "kuhul://phases/xul",
            "aiml": [], "bindings": [], "next": None, "authority": "declaration_only"}),
            encoding="utf-8")
        with FakeModelServer() as fake:
            router = router_with(fake.base_url)
            plan = model_router.plan_invocation(router, "commit the tree", granted=set(),
                                                folder=folder)
        self.assertFalse(plan["invoke_model"])
        self.assertEqual(plan["routing_action"], "refuse")
        self.assertIn("cannot override", plan["reason"])

    def test_an_unhandled_turn_proposes_the_model(self):
        with FakeModelServer() as fake:
            router = router_with(fake.base_url)
            plan = model_router.plan_invocation(router, "explain quantum chromodynamics", granted=READ)
        self.assertTrue(plan["invoke_model"], plan)
        self.assertEqual(plan["binding"]["selected"], "advisor",
                         "this temp manifest routes compose to the advisor")
        self.assertFalse(plan["execution"])


if __name__ == "__main__":
    unittest.main()
