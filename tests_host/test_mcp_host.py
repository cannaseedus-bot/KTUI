"""M92: KTUI's read-only handlers exposed over MCP, and nothing more.

The protocol surface is checked through the SDK's own in-memory client, so this is a real MCP conversation and not a
direct function call. Three properties matter: only registered read-only handlers are invocable, a route is resolved
and never dispatched, and every result says admitted false.
"""
import asyncio
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mcp_host  # noqa: E402

try:
    from mcp.shared.memory import create_connected_server_and_client_session
    HAVE_SDK = True
except ImportError:  # the SDK is optional: the host must still import and describe itself
    HAVE_SDK = False


def tool_payload(result) -> dict:
    return json.loads(result.content[0].text)


class SurfaceTests(unittest.TestCase):
    def test_the_host_describes_itself_without_a_connection(self):
        server, version = mcp_host.build_server()
        self.assertIn(version, ("v1", "v2"))
        self.assertIsNotNone(server)

    def test_every_exposable_handler_is_read_only(self):
        listing = mcp_host.list_handlers()
        self.assertTrue(listing["ok"], listing["problems"])
        self.assertGreater(listing["count"], 0)
        for row in listing["handlers"]:
            self.assertEqual(row["exposable"], row["effect"] == "read_only", row["uri"])
        self.assertGreater(listing["exposable"], 0)

    def test_an_unknown_handler_is_refused(self):
        result = mcp_host.invoke_readonly("micronaut://v1/nothing", {})
        self.assertEqual(result["refused"], "handler_not_registered")
        self.assertFalse(result["admitted"])

    def test_an_untyped_payload_is_refused_by_the_host_contract(self):
        result = mcp_host.invoke_readonly("micronaut://v1/aiml", {"text": "hello"})
        self.assertFalse(result["ok"])
        self.assertIn("payload_schema_mismatch", result["detail"])

    def test_a_typed_payload_invokes_a_read_only_handler(self):
        result = mcp_host.invoke_readonly("micronaut://v1/aiml",
                                          {"$schema": "kuhul://schema/utterance/v1", "text": "hello"})
        self.assertTrue(result["ok"], result.get("detail"))
        self.assertEqual(result["result"]["payload"]["$schema"], "kuhul://schema/candidates/v1")
        self.assertFalse(result["admitted"])

    def test_a_route_is_resolved_by_spoken_name_and_never_dispatched(self):
        resolved = mcp_host.resolve_route("ASK PLANNER")
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["target"], "model://planner")
        self.assertEqual(resolved["output_type"], "candidate_text")
        self.assertFalse(resolved["admitted"])
        self.assertNotIn("result", resolved, "resolution must not produce a dispatched result")

    def test_text_that_looks_like_a_route_is_refused(self):
        self.assertEqual(mcp_host.resolve_route("model://planner")["refused"], "route_not_declared")
        self.assertEqual(mcp_host.resolve_route("what is model://planner")["refused"], "route_not_declared")


@unittest.skipUnless(HAVE_SDK, "the MCP SDK is required for the protocol surface")
class ProtocolTests(unittest.TestCase):
    def run_client(self, body):
        async def drive():
            server, _version = mcp_host.build_server()
            async with create_connected_server_and_client_session(server) as client:
                return await body(client)

        return asyncio.run(drive())

    def test_the_declared_surface_is_exposed(self):
        async def body(client):
            tools = await client.list_tools()
            resources = await client.list_resources()
            return ([tool.name for tool in tools.tools],
                    sorted(str(resource.uri) for resource in resources.resources))

        tools, resources = self.run_client(body)
        self.assertEqual(sorted(tools), ["kuhul_invoke_readonly", "kuhul_list_handlers", "kuhul_resolve_route"])
        self.assertEqual(resources, ["kuhul://host/authority", "kuhul://phases/last", "kuhul://runtime/tree"])

    def test_the_authority_resource_states_the_limits(self):
        async def body(client):
            read = await client.read_resource("kuhul://host/authority")
            return json.loads(read.contents[0].text)

        authority = self.run_client(body)
        self.assertEqual(authority["authority"], "declaration_only")
        self.assertFalse(authority["admitted"])
        self.assertFalse(authority["execution"])
        self.assertFalse(authority["mutation"])
        self.assertEqual(authority["effect_policy"], "read_only")

    def test_a_tool_call_returns_a_typed_json_result(self):
        async def body(client):
            return tool_payload(await client.call_tool("kuhul_list_handlers", {}))

        listing = self.run_client(body)
        self.assertTrue(listing["ok"])
        self.assertEqual(listing["schema"], mcp_host.SCHEMA)

    def test_a_bad_payload_is_reported_not_raised(self):
        async def body(client):
            return tool_payload(await client.call_tool("kuhul_invoke_readonly",
                                                       {"uri": "micronaut://v1/aiml", "payload_json": "not json"}))

        result = self.run_client(body)
        self.assertEqual(result["refused"], "payload_not_json")

    def test_route_resolution_over_the_protocol_matches_the_function(self):
        async def body(client):
            return tool_payload(await client.call_tool("kuhul_resolve_route", {"route_name": "ASK PLANNER"}))

        over_protocol = self.run_client(body)
        direct = mcp_host.resolve_route("ASK PLANNER")
        self.assertEqual(over_protocol["target"], direct["target"])
        self.assertFalse(over_protocol["admitted"])


class PreferenceAndMountTests(unittest.TestCase):
    """The MCP surface resolves the agent's preferences, and the server can host it in one process."""

    def test_a_preference_word_resolves_through_the_agent_declaration(self):
        resolved = mcp_host.resolve_route("REASONING")
        self.assertTrue(resolved["ok"], resolved.get("refused"))
        self.assertEqual(resolved["target"], "model://planner")
        self.assertFalse(resolved["admitted"])
        self.assertEqual(mcp_host.resolve_route("CONVERSATION")["target"], "model://worker")

    def test_a_preference_still_cannot_be_a_target(self):
        self.assertEqual(mcp_host.resolve_route("model://planner")["refused"], "route_not_declared")

    def test_the_server_can_start_the_mcp_surface_in_its_own_process(self):
        import inspect

        import micronaut_server

        self.assertTrue(hasattr(micronaut_server, "start_mcp"))
        self.assertIn("port", inspect.signature(micronaut_server.start_mcp).parameters)
        # main must accept the flag without touching this process's listeners
        parser_defaults = inspect.signature(micronaut_server.main).parameters
        self.assertIn("argv", parser_defaults)

    def test_starting_the_mcp_surface_reports_a_url_without_serving_forever(self):
        import micronaut_server

        started = micronaut_server.start_mcp(0)      # port 0: the OS picks one
        try:
            self.assertTrue(started["url"].startswith("http://127.0.0.1:"))
            self.assertTrue(started["url"].endswith("/mcp"))
            self.assertIn(started["sdk"], ("v1", "v2"))
            self.assertTrue(started["thread"].daemon, "a daemon thread dies with the daemon")
        finally:
            started["server"].should_exit = True
            started["thread"].join(timeout=10)


if __name__ == "__main__":
    unittest.main()
