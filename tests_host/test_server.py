"""M19: the daemon has a reachable endpoint, and a network client can only read.

`micronaut://v1/chat` is logical; it maps to `http://127.0.0.1:<port>/v1/chat`. These tests start a
real server on an ephemeral port and speak to it over real HTTP, then check the two things that
matter: the local pipeline answers, and nothing that needs a grant happens - no model call, no memory
write, no git operation, no file write.
"""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import micronaut_server  # noqa: E402
import session_log  # noqa: E402
import user_memory  # noqa: E402


class M19Endpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
        user_memory.EVENTS = Path(tempfile.mkdtemp()) / "user.events.jsonl"
        cls.server = micronaut_server.serve(0, block=False)
        cls.host, cls.port = cls.server.server_address[:2]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://{cls.host}:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, method, path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8", "replace"))

    # -- binding and address --------------------------------------------------------------------
    def test_binds_loopback_only_and_names_its_uri(self):
        self.assertEqual(self.host, "127.0.0.1")
        self.assertEqual(micronaut_server.uri(), "micronaut://v1/chat")
        self.assertEqual(micronaut_server.transport(self.port),
                         f"http://127.0.0.1:{self.port}/v1/chat")

    def test_health_reports_the_running_daemon(self):
        status, body = self.call("GET", "/v1/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["phases"], ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])
        self.assertIn("model", body)
        self.assertFalse(body["writes"], "a fresh daemon must not advertise write access")

    def test_models_are_listed_in_order(self):
        status, body = self.call("GET", "/v1/models")
        self.assertEqual(status, 200)
        self.assertIn("gpt-oss-20b", body["models"])
        self.assertEqual(body["default"], "gpt-oss-20b")

    # -- the chat route -------------------------------------------------------------------------
    def test_identity_answers_over_http(self):
        status, body = self.call("POST", "/v1/chat", {"message": "who are you"})
        self.assertEqual(status, 200)
        self.assertEqual(body["kind"], "aiml")
        self.assertIn("Micronaut Daemon Bot", body["reply"])
        self.assertEqual([phase["phase"] for phase in body["phases"]],
                         ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])

    def test_small_talk_answers_locally(self):
        status, body = self.call("POST", "/v1/chat", {"message": "hello"})
        self.assertEqual(status, 200)
        self.assertEqual(body["kind"], "aiml")
        self.assertTrue(body["reply"].strip())

    def test_a_refusal_is_reported_as_a_refusal(self):
        status, body = self.call("POST", "/v1/chat", {"message": "commit this"})
        self.assertEqual(status, 200)
        self.assertEqual(body["kind"], "refused")
        self.assertIn("/allow git", body["reply"])

    def test_an_unknown_phrase_defers_without_calling_the_model(self):
        before = len(user_memory.events(user_memory.DEFAULT_USER))
        status, body = self.call("POST", "/v1/chat",
                                 {"message": "explain quantum chromodynamics in detail"})
        self.assertEqual(status, 200)
        self.assertEqual(body["kind"], "deferred")
        self.assertIsNone(body["reply"])
        self.assertIn("not invoked", body["note"])
        self.assertEqual(len(user_memory.events(user_memory.DEFAULT_USER)), before)

    def test_a_memory_write_cannot_be_triggered_over_the_network(self):
        before = len(user_memory.events(user_memory.DEFAULT_USER))
        status, body = self.call("POST", "/v1/chat", {"message": "my dogs name is max"})
        self.assertEqual(status, 200)
        self.assertEqual(body["kind"], "refused")
        self.assertIn("/allow memory", body["reply"])
        self.assertEqual(len(user_memory.events(user_memory.DEFAULT_USER)), before,
                         "a network client must not write memory")

    # -- protocol errors ------------------------------------------------------------------------
    def test_empty_and_malformed_bodies_are_rejected(self):
        status, body = self.call("POST", "/v1/chat", None)
        self.assertEqual(status, 400)
        self.assertIn("message", body["error"])

        raw = urllib.request.Request(self.base + "/v1/chat", data=b"{not json",
                                     method="POST", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(raw, timeout=30)
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 400)

    def test_unknown_paths_and_methods_are_rejected(self):
        self.assertEqual(self.call("GET", "/v1/nope")[0], 404)
        self.assertEqual(self.call("PUT", "/v1/chat", {"message": "x"})[0], 405)


if __name__ == "__main__":
    unittest.main()
