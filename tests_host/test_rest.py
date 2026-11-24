"""M37: `kuhul-rest/v1` - a projection of authorized data, with the four guards.

The completion criterion from the review, as a test: `GET /api/users/42` walks route manifest ->
authorization -> projection -> HTTP 200 with JSON, and no field appears that the projection does not
allow.

Negative cases are the point: unknown routes are 404, malformed parameters 400, missing grants 403, a
cross-user read 403, and a fact that was never recorded stays missing.
"""
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import micronaut_server  # noqa: E402
import rest_adapter  # noqa: E402
import session_log  # noqa: E402
import user_memory  # noqa: E402

READ = {"graph.relations.read"}


class RestRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        user_memory.EVENTS = Path(cls.folder.name) / "user.events.jsonl"
        session_log.SESSIONS_DIR = Path(cls.folder.name) / "sessions"
        for predicate, value in (("name", "Bill"), ("status", "active"),
                                 ("email", "bill@example.com")):
            user_memory.remember(user="42", subject="user", predicate=predicate, value=value)
        cls.manifest = rest_adapter.load()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def call(self, path, *, caller="42", granted=READ):
        return rest_adapter.handle("GET", path, caller=caller, granted=granted,
                                   manifest=self.manifest)

    # -- the manifest ------------------------------------------------------------------------------
    def test_the_manifest_is_declaration_only_and_effect_free(self):
        self.assertTrue(self.manifest["ok"], self.manifest["problems"])
        self.assertEqual(self.manifest["authority"], "declaration_only")
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "rest-routes.json")
                            .read_text(encoding="utf-8"))
        for route in record["routes"]:
            self.assertEqual(route["effects"], {"execution": False, "mutation": False,
                                                "persistence": False}, route["path"])

    def test_a_manifest_that_could_execute_is_refused(self):
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "rest-routes.json")
                            .read_text(encoding="utf-8"))
        record["routes"][0]["effects"]["mutation"] = True
        path = Path(self.folder.name) / "bad-routes.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        report = rest_adapter.load(path)
        self.assertFalse(report["ok"])
        self.assertIn("effects", [problem["code"] for problem in report["problems"]])

    # -- guard 1: route confinement ----------------------------------------------------------------
    def test_unknown_routes_and_methods_are_404(self):
        self.assertEqual(self.call("/api/nope")["status"], 404)
        self.assertEqual(self.call("/api/users")["status"], 404)
        self.assertEqual(rest_adapter.handle("POST", "/api/users/42", caller="42",
                                             granted=READ, manifest=self.manifest)["status"], 404)

    def test_parameters_are_typed_not_arbitrary_text(self):
        malformed = self.call("/api/users/42x")
        self.assertEqual(malformed["status"], 400)
        self.assertIn("expected integer", malformed["error"])
        self.assertEqual(self.call("/api/phases/9bad")["status"], 400)

    # -- guard 2: read authorization ---------------------------------------------------------------
    def test_a_missing_capability_is_403(self):
        refused = self.call("/api/users/42", granted=set())
        self.assertEqual(refused["status"], 403)
        self.assertIn("not granted", refused["error"])

    def test_the_manifest_capability_maps_onto_the_host_grant(self):
        # Either name works: the manifest's own, or the host capability it aliases.
        for granted in ({"memory.facts.read"}, {"graph.relations.read"}):
            self.assertEqual(self.call("/api/users/42", granted=granted)["status"], 200, granted)
        unrelated = self.call("/api/users/42", granted={"repo.write"})
        self.assertEqual(unrelated["status"], 403, "an unrelated grant does not cover the route")

    def test_a_caller_may_not_read_another_user(self):
        cross = self.call("/api/users/99", caller="42")
        self.assertEqual(cross["status"], 403)
        self.assertIn("may not read", cross["error"])
        wider = self.call("/api/users/42", caller="42", granted=READ | {"users.read.any"})
        self.assertEqual(wider["status"], 200)
        as_admin = self.call("/api/users/42", caller="99", granted=READ | {"users.read.any"})
        self.assertEqual(as_admin["status"], 200)

    def test_an_anonymous_caller_is_refused(self):
        self.assertEqual(self.call("/api/users/42", caller="")["status"], 403)

    # -- guard 3: projection confinement -----------------------------------------------------------
    def test_only_permitted_fields_are_returned(self):
        result = self.call("/api/users/42")
        self.assertEqual(result["status"], 200)
        self.assertEqual(sorted(result["body"]), ["id", "name", "status"])
        self.assertNotIn("email", result["body"], "a private fact must not leak")
        self.assertIn("email", result["withheld"])

    def test_a_missing_fact_stays_missing(self):
        user_memory.remember(user="7", subject="user", predicate="status", value="idle")
        result = self.call("/api/users/7", caller="7")
        self.assertEqual(result["status"], 200)
        self.assertEqual(sorted(result["body"]), ["id", "status"],
                         "no invented name: the fact was never recorded")

    def test_a_resource_with_no_records_is_404(self):
        # the caller reads their own id, which exists as an identity but has no facts
        self.assertEqual(self.call("/api/users/4242", caller="4242")["status"], 404)

    # -- guard 4: effect confinement ---------------------------------------------------------------
    def test_a_get_reports_no_effects(self):
        result = self.call("/api/users/42")
        self.assertFalse(result["execution"])
        self.assertFalse(result["mutation"])
        self.assertFalse(result["persistence"])
        self.assertEqual(result["authority"], "declaration_only")

    def test_the_operator_pipeline_runs_over_facts(self):
        result = self.call("/api/users/42")
        self.assertEqual(result["pipeline"], ["filter", "map", "fold", "reduce"])

    # -- the completion criterion, over real HTTP ---------------------------------------------------
    def test_end_to_end_over_http(self):
        server = micronaut_server.serve(0, block=False)
        host, port = server.server_address[:2]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/api/users/42?as=42", timeout=30) as response:
                status, body = response.status, json.loads(response.read().decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(sorted(body["body"]), ["id", "name", "status"])
            self.assertNotIn("email", body["body"])
            try:
                urllib.request.urlopen(f"http://{host}:{port}/api/users/42x?as=42", timeout=30)
                self.fail("a malformed parameter must not return 200")
            except urllib.error.HTTPError as error:
                self.assertEqual(error.code, 400)
        finally:
            server.shutdown()
            server.server_close()

    def test_the_response_is_deterministic(self):
        first = json.dumps(self.call("/api/users/42"), sort_keys=True)
        second = json.dumps(self.call("/api/users/42"), sort_keys=True)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
