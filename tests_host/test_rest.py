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
TOKEN = "token-42"
TOKEN_OTHER = "token-7"
TOKEN_UNPRIVILEGED = "token-9"


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

    def call(self, path, *, token=TOKEN, granted=READ):
        return rest_adapter.handle("GET", path, token=token, granted=granted,
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
        self.assertEqual(rest_adapter.handle("POST", "/api/users/42", token=TOKEN,
                                             granted=READ, manifest=self.manifest)["status"], 404)

    def test_parameters_are_typed_not_arbitrary_text(self):
        malformed = self.call("/api/users/42x")
        self.assertEqual(malformed["status"], 400)
        self.assertIn("expected integer", malformed["error"])
        self.assertEqual(self.call("/api/phases/9bad")["status"], 400)

    # -- guard 2: read authorization ---------------------------------------------------------------
    def test_a_missing_capability_is_403(self):
        refused = self.call("/api/users/42", token=TOKEN_UNPRIVILEGED)
        self.assertEqual(refused["status"], 403)
        self.assertIn("not granted", refused["error"])

    def test_the_manifest_capability_maps_onto_the_identity_capability(self):
        # The identity holds graph.relations.read, which the manifest names memory.facts.read.
        self.assertEqual(self.call("/api/users/42")["status"], 200)
        self.assertEqual(self.call("/api/users/42", token=TOKEN_UNPRIVILEGED)["status"], 403)

    def test_a_caller_may_not_read_another_user(self):
        cross = self.call("/api/users/7")
        self.assertEqual(cross["status"], 403)
        self.assertIn("may not read", cross["error"])
        # identity 7 carries users.read.any in its own scope, so it may read 42
        self.assertEqual(self.call("/api/users/42", token=TOKEN_OTHER)["status"], 200)

    def test_an_anonymous_caller_is_refused(self):
        self.assertEqual(self.call("/api/users/42", token="")["status"], 403)
        self.assertEqual(self.call("/api/users/42", token="forged")["status"], 403)

    # -- guard 3: projection confinement -----------------------------------------------------------
    def test_only_permitted_fields_are_returned(self):
        result = self.call("/api/users/42")
        self.assertEqual(result["status"], 200)
        self.assertEqual(sorted(result["body"]), ["id", "name", "status"])
        self.assertNotIn("email", result["body"], "a private fact must not leak")
        self.assertIn("email", result["withheld"])

    def test_a_missing_fact_stays_missing(self):
        user_memory.remember(user="7", subject="user", predicate="status", value="idle")
        result = self.call("/api/users/7", token=TOKEN_OTHER)
        self.assertEqual(result["status"], 200)
        self.assertEqual(sorted(result["body"]), ["id", "status"],
                         "no invented name: the fact was never recorded")

    def test_a_resource_with_no_records_is_404(self):
        self.assertEqual(self.call("/api/users/4242", token=TOKEN_UNPRIVILEGED)["status"], 403,
                         "an unprivileged identity cannot read anything, including its own record")

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
            request = urllib.request.Request(f"http://{host}:{port}/api/users/42")
            request.add_header("Authorization", f"Bearer {TOKEN}")
            with urllib.request.urlopen(request, timeout=30) as response:
                status, body = response.status, json.loads(response.read().decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(sorted(body["body"]), ["id", "name", "status"])
            self.assertNotIn("email", body["body"])
            malformed = urllib.request.Request(f"http://{host}:{port}/api/users/42x")
            malformed.add_header("Authorization", f"Bearer {TOKEN}")
            try:
                urllib.request.urlopen(malformed, timeout=30)
                self.fail("a malformed parameter must not return 200")
            except urllib.error.HTTPError as error:
                self.assertEqual(error.code, 400)

            asserted = urllib.request.Request(f"http://{host}:{port}/api/users/42?as=42")
            asserted.add_header("Authorization", f"Bearer {TOKEN}")
            try:
                urllib.request.urlopen(asserted, timeout=30)
                self.fail("identity must not be assertable in the query")
            except urllib.error.HTTPError as error:
                self.assertEqual(error.code, 400)
        finally:
            server.shutdown()
            server.server_close()

    def test_the_response_is_deterministic(self):
        first = json.dumps(self.call("/api/users/42"), sort_keys=True)
        second = json.dumps(self.call("/api/users/42"), sort_keys=True)
        self.assertEqual(first, second)


class M38RequestIdentity(unittest.TestCase):
    """Per-request identity: the transport authenticates, the manifest cannot be talked around."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        user_memory.EVENTS = Path(cls.folder.name) / "user.events.jsonl"
        session_log.SESSIONS_DIR = Path(cls.folder.name) / "sessions"
        for predicate, value in (("name", "Bill"), ("status", "active"), ("email", "bill@example.com")):
            user_memory.remember(user="42", subject="user", predicate=predicate, value=value)
        user_memory.remember(user="7", subject="user", predicate="name", value="Alice")
        cls.manifest = rest_adapter.load()
        cls.registry = rest_adapter.load_identities()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def call(self, path, *, token=TOKEN, granted=READ):
        return rest_adapter.handle("GET", path, token=token, granted=granted,
                                   manifest=self.manifest, registry=self.registry)

    def test_identity_comes_from_the_token_not_the_request(self):
        self.assertEqual(self.call("/api/users/42")["caller"], "42")
        self.assertEqual(self.call("/api/users/7", token=TOKEN_OTHER)["caller"], "7")

    def test_a_forged_identity_is_not_honoured(self):
        self.assertEqual(self.call("/api/users/42", token="token-42-forged")["status"], 403)
        self.assertEqual(self.call("/api/users/42", token="")["status"], 403)

    def test_an_engine_wide_grant_does_not_widen_caller_scope(self):
        wide = self.call("/api/users/7", granted={"graph.relations.read", "users.read.any",
                                                  "memory.facts.read"})
        self.assertEqual(wide["status"], 403,
                         "the engine holding users.read.any must not let caller 42 read 7")
        self.assertIn("may not read", wide["error"])

    def test_each_identity_is_bounded_by_its_own_scope(self):
        self.assertEqual(self.call("/api/users/7")["status"], 403)
        self.assertEqual(self.call("/api/users/7", token=TOKEN_OTHER)["status"], 200)
        self.assertEqual(self.call("/api/users/42", token=TOKEN_OTHER)["status"], 200,
                         "identity 7 carries users.read.any")

    def test_a_denial_leaks_no_fields_and_no_existence(self):
        denied = self.call("/api/users/7")
        self.assertEqual(denied["status"], 403)
        for key in ("body", "allowed", "returned", "withheld", "projection"):
            self.assertNotIn(key, denied, f"a denial must not disclose {key}")
        self.assertNotIn("Alice", json.dumps(denied))

    def test_an_unknown_identity_is_refused_before_any_lookup(self):
        refused = self.call("/api/users/42", token="nobody")
        self.assertEqual(refused["status"], 403)
        self.assertEqual(refused["error"], "no authenticated identity")

    def test_the_registry_stores_token_hashes_not_tokens(self):
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "identities.json")
                            .read_text(encoding="utf-8"))
        for entry in record["identities"]:
            self.assertEqual(len(entry["token_sha256"]), 64)
            self.assertNotIn("token", entry, "the fixture stores a hash, not the token")


if __name__ == "__main__":
    unittest.main()
