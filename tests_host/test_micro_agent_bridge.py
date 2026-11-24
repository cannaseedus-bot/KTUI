"""M90: the Micro Agent bridge - one dispatch contract, two destinations, and text is never a route.

The integration test the review specified: an AIML/SRAI chain resolves a declared route name, the host resolves it
against the model registry, dispatches through the injected inference function, and returns candidate text. Missing
grants, unknown aliases, undeclared names and ordinary text containing a URI invoke nothing - and a persona cannot
widen a grant.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import micro_agent_bridge as bridge  # noqa: E402
import srai_resolver  # noqa: E402

PATTERNS = {"ASK PLANNER": "SRAI ASK_PLANNER", "ASK_PLANNER": "ROUTE ASK_PLANNER"}


def lookup(pattern):
    return PATTERNS.get(pattern.strip().upper())


class Spy:
    def __init__(self, text="PLAN: filter, then fold."):
        self.calls = []
        self.text = text

    def complete(self, alias, payload):
        self.calls.append(("model", alias, payload))
        return self.text

    def invoke(self, uri, payload):
        self.calls.append(("micronaut", uri, payload))
        return {"relations": 3}


class RouteResolutionTests(unittest.TestCase):
    def test_an_srai_chain_resolves_a_declared_route_name(self):
        resolved = srai_resolver.resolve("ASK PLANNER", [], lookup, max_depth=4)
        self.assertEqual(resolved["reply"], "ROUTE ASK_PLANNER")
        self.assertEqual(len(resolved["trace"]), 2, "two hops, both recorded")
        name = resolved["reply"].replace("ROUTE ", "")
        route = bridge.resolve(name, declaration=bridge.DECLARED_ROUTES)
        self.assertTrue(route["ok"])
        self.assertEqual(route["scheme"], "model")
        self.assertEqual(route["target"], "model://planner")
        self.assertEqual(route["output_type"], "candidate_text")

    def test_text_is_not_a_route(self):
        self.assertEqual(bridge.route_from_text("model://planner")["refused"], "text_is_not_a_route")

    def test_an_undeclared_name_is_refused(self):
        route = bridge.resolve("model://planner", declaration=bridge.DECLARED_ROUTES)
        self.assertFalse(route["ok"])
        self.assertEqual(route["refused"], "route_not_declared")

    def test_an_unregistered_alias_is_refused(self):
        declaration = {"ASK_GHOST": dict(scheme="model", target="model://ghost", alias="ghost",
                                         capability="model.inference", output_type="candidate_text")}
        route = bridge.resolve("ASK_GHOST", declaration=declaration)
        self.assertEqual(route["refused"], "unknown_target")

    def test_declared_routes_only_name_registered_schemes(self):
        for name, entry in bridge.DECLARED_ROUTES.items():
            self.assertTrue(entry["target"].startswith(("model://", "micronaut://")), name)
            self.assertIn(entry["output_type"], bridge.OUTPUT_TYPES, name)


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.spy = Spy()

    def run_route(self, name, *, grants=("model.inference",), payload=None, **kwargs):
        return bridge.run(name, payload or {"text": "summarise my tasks"}, grants=set(grants),
                          request_id="turn-1", complete_for=self.spy.complete,
                          invoke_for=self.spy.invoke, **kwargs)

    def test_a_declared_model_route_dispatches_and_returns_candidate_text(self):
        result = self.run_route("ASK_PLANNER")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["source"], "aiml_srai")
        self.assertEqual(result["output_type"], "candidate_text")
        self.assertEqual(result["result"], "PLAN: filter, then fold.")
        self.assertFalse(result["admitted"], "the dispatch was authorised; the result grants nothing")
        self.assertEqual(self.spy.calls, [("model", "planner", {"text": "summarise my tasks"})])

    def test_a_missing_grant_invokes_nothing(self):
        result = self.run_route("ASK_PLANNER", grants=())
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["refused"], "capability_not_granted")
        self.assertEqual(self.spy.calls, [])

    def test_a_persona_cannot_widen_a_grant(self):
        result = self.run_route("ASK_PLANNER", grants=(),
                                persona={"capabilities": ["model.inference"], "name": "daemon-bot"})
        self.assertEqual(result["refused"], "capability_not_granted")
        self.assertEqual(self.spy.calls, [])

    def test_text_containing_a_uri_invokes_nothing(self):
        result = bridge.run("model://planner", {}, grants={"model.inference"}, request_id="t",
                            complete_for=self.spy.complete)
        self.assertEqual(result["refused"], "route_not_declared")
        self.assertEqual(self.spy.calls, [])

    def test_the_micronaut_destination_returns_a_typed_result(self):
        result = self.run_route("QUERY_RELATIONS", grants=("graph.relations.read",),
                                payload={"operation": "inventory"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["scheme"], "micronaut")
        self.assertEqual(result["output_type"], "typed_result")
        self.assertEqual(result["result"], {"relations": 3})
        self.assertEqual(self.spy.calls, [("micronaut", "micronaut://gml/graph-theory/query",
                                          {"operation": "inventory"})])

    def test_a_missing_dispatcher_is_refused_not_crashed(self):
        result = bridge.run("ASK_PLANNER", {}, grants={"model.inference"}, request_id="t")
        self.assertEqual(result["refused"], "dispatcher_unavailable")

    def test_an_empty_candidate_is_a_failure(self):
        blocker = Spy(text="   ")
        result = bridge.run("ASK_WORKER", {}, grants={"model.inference"}, request_id="t",
                            complete_for=blocker.complete)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["refused"], "empty_candidate")

    def test_a_dispatch_exception_is_a_failed_route(self):
        def broken(alias, payload):
            raise TimeoutError("backend did not answer")

        result = bridge.run("ASK_PLANNER", {}, grants={"model.inference"}, request_id="t",
                            complete_for=broken)
        self.assertEqual(result["status"], "failed")
        self.assertIn("TimeoutError", result["detail"])

    def test_every_result_stays_declarative(self):
        for name, grants in (("ASK_PLANNER", {"model.inference"}), ("QUERY_RELATIONS", set())):
            result = self.run_route(name, grants=grants)
            self.assertFalse(result["admitted"])
            self.assertEqual(result["authority"], "declaration_only")
            self.assertEqual(result["request_id"], "turn-1")

    def test_a_persona_that_is_not_metadata_is_refused(self):
        route = bridge.resolve("ASK_PLANNER", declaration=bridge.DECLARED_ROUTES)
        result = bridge.dispatch(route, {}, grants={"model.inference"}, request_id="t",
                                 complete_for=self.spy.complete, persona=["model.inference"])
        self.assertEqual(result["refused"], "persona_invalid")
        self.assertEqual(self.spy.calls, [])


if __name__ == "__main__":
    unittest.main()
