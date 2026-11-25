"""MCP host for KTUI: the registered, read-only handlers, exposed over the Model Context Protocol.

This is an **exposure** layer, not a second authority. Three rules it keeps, which are the ones this project has
already paid for:

    read-only only      a tool exists only for a handler whose declared effect is read_only
    declared only       a handler URI must be in the registry; nothing is resolved from free text
    declaration_only    every result says admitted: false - the protocol grants nothing downstream

It speaks whichever SDK is installed: v2 (`mcp.server.MCPServer`) when present, v1 (`FastMCP`) otherwise. The tool
and resource names are identical on both, so a host sees the same surface either way.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import micro_agent_bridge  # noqa: E402
import micronaut_host_handlers  # noqa: E402

SCHEMA = "kuhul://mcp/host/v1"
SERVER_NAME = "kuhul-ktui"
AUTHORITY = "declaration_only"


def _sdk() -> tuple[str, object]:
    """Which SDK this interpreter has: v2 first, v1 second. Named so a caller can report it."""
    try:
        from mcp.server import MCPServer        # v2
        return "v2", MCPServer
    except ImportError:
        from mcp.server.fastmcp import FastMCP  # v1
        return "v1", FastMCP


def _host(granted: set | None = None) -> object:
    """One host, with the read-only policy this exposure is allowed to have."""
    return micronaut_host_handlers.HandlerHost(
        identity="kuhul-ktui-mcp", granted=set(granted or ()),
        policy=lambda binding, payload: getattr(binding, "effect", None) == "read_only")


def registry() -> dict:
    """The handler registry, as the host sees it - the source of truth for what may be exposed."""
    try:
        return _host().registry
    except Exception as error:                     # a broken registry must be reported, not raised
        return dict(ok=False, by_uri={}, problems=[dict(code="registry_unavailable", detail=str(error)[:200])])


def bindings() -> dict:
    """The typed bindings: the only place the declared effect is actually recorded."""
    host = _host()
    return dict(getattr(host, "bindings", {}) or {})


def list_handlers() -> dict:
    """Every registered handler, with the effect that decides whether it may be invoked here."""
    record = registry()
    typed = bindings()
    rows = []
    for uri, entry in sorted((record.get("by_uri") or {}).items()):
        binding = typed.get(uri)
        effect = getattr(binding, "effect", None)
        rows.append(dict(uri=uri, capability=getattr(binding, "capability", None),
                         effect=effect,
                         role=entry.get("role"), entry=entry.get("entry"),
                         input_schema=entry.get("input_schema"), output_schema=entry.get("output_schema"),
                         exposable=(effect == "read_only")))
    return dict(schema=SCHEMA, ok=bool(record.get("ok")), count=len(rows), handlers=rows,
                exposable=sum(1 for row in rows if row["exposable"]),
                problems=record.get("problems") or [], authority=AUTHORITY, admitted=False)


def invoke_readonly(uri: str, payload: dict | None = None) -> dict:
    """Invoke one registered read-only handler. A write-effect handler is refused, not attempted."""
    typed = bindings()
    binding = typed.get(str(uri or ""))
    if binding is None:
        return dict(schema=SCHEMA, ok=False, refused="handler_not_registered", uri=uri,
                    detail="the URI is not in the handler registry", authority=AUTHORITY, admitted=False)
    effect = getattr(binding, "effect", None)
    if effect != "read_only":
        return dict(schema=SCHEMA, ok=False, refused="effect_not_read_only", uri=uri,
                    detail=f"declared effect is {effect!r}; MCP exposure is read-only",
                    authority=AUTHORITY, admitted=False)
    try:
        host = _host({getattr(binding, "capability", None)})
        body = payload or {}
        # Admission is granted by the host, for this URI and this payload only.
        result = host.invoke(host.admit(str(uri), body), body)
    except Exception as error:
        return dict(schema=SCHEMA, ok=False, refused="invocation_error", uri=uri,
                    detail=f"{type(error).__name__}: {error}"[:200], authority=AUTHORITY, admitted=False)
    return dict(schema=SCHEMA, ok=True, refused=None, uri=uri, result=result, authority=AUTHORITY,
                admitted=False)


def spoken_to_route(spoken: str) -> str | None:
    """Translate what a person typed into a declared route name, through the SRAI chain (two hops)."""
    try:
        import srai_resolver
    except ImportError:
        return None

    def lookup(pattern: str) -> str | None:
        text = str(pattern or "").strip().upper()
        for name in micro_agent_bridge.DECLARED_ROUTES:
            if text == name:
                return f"ROUTE {name}"
            if text.replace(" ", "_") == name:
                return f"SRAI {name}"
        return None

    try:
        reply = srai_resolver.resolve(str(spoken or "").strip().upper(), [], lookup, max_depth=3)["reply"]
    except Exception:
        return None
    return reply[len("ROUTE "):].strip() if str(reply or "").startswith("ROUTE ") else None


PREFERENCE_WORDS = {"REASON": "reasoning", "REASONING": "reasoning",
                    "CONVERSATION": "conversation", "RELATIONS": "relations"}


def preference_route(word: str) -> str | None:
    """The Micro Agent's preferred declared route for a kind of work, if its declaration is valid."""
    kind = PREFERENCE_WORDS.get(str(word or "").strip().upper())
    if not kind:
        return None
    try:
        import agent_profile

        return agent_profile.route_for(kind)
    except Exception:
        return None


def resolve_route(route_name: str) -> dict:
    """Resolve a declared bridge route - resolution only. Dispatch stays with the host, not the protocol."""
    name = (preference_route(route_name) or spoken_to_route(route_name)
            or str(route_name or "").strip())
    resolved = micro_agent_bridge.resolve(name, declaration=micro_agent_bridge.DECLARED_ROUTES)
    return dict(schema=SCHEMA, ok=bool(resolved.get("ok")), refused=resolved.get("refused"),
                route=resolved.get("route") or str(route_name or ""), scheme=resolved.get("scheme"),
                target=resolved.get("target"), output_type=resolved.get("output_type"),
                required_capability=resolved.get("capability"),
                detail=resolved.get("detail"), authority=AUTHORITY, admitted=False)


def runtime_tree() -> dict:
    """The runtime projection, read-only, for a host that wants to see what is warm and leased."""
    try:
        import runtime_tree as tree

        observed = tree.observed() if hasattr(tree, "observed") else {}
        return dict(schema=SCHEMA, ok=True, tree=observed, authority=AUTHORITY, admitted=False)
    except Exception as error:
        return dict(schema=SCHEMA, ok=False, refused="unavailable",
                    detail=f"{type(error).__name__}: {error}"[:200], authority=AUTHORITY, admitted=False)


def last_phases() -> dict:
    """The most recent observed phase trace, if any - what the host actually did, never a prediction."""
    try:
        import phase_events

        traces = getattr(phase_events, "_traces", {}) or {}
        if not traces:
            return dict(schema=SCHEMA, ok=True, traces=[], last=None, authority=AUTHORITY, admitted=False)
        request_id = next(reversed(traces))
        return dict(schema=SCHEMA, ok=True, last=phase_events.observe(request_id),
                    traces=list(traces)[-8:], authority=AUTHORITY, admitted=False)
    except Exception as error:
        return dict(schema=SCHEMA, ok=False, refused="unavailable",
                    detail=f"{type(error).__name__}: {error}"[:200], authority=AUTHORITY, admitted=False)


def build_server():
    """The MCP server object, with the tool and resource surface this host exposes."""
    version, sdk = _sdk()
    server = sdk(SERVER_NAME)

    @server.tool()
    def kuhul_list_handlers() -> str:
        """List the registered Micronaut handlers and whether each may be invoked through MCP."""
        return json.dumps(list_handlers(), sort_keys=True)

    @server.tool()
    def kuhul_invoke_readonly(uri: str, payload_json: str = "{}") -> str:
        """Invoke one registered READ-ONLY handler by URI. Write-effect handlers are refused."""
        try:
            payload = json.loads(payload_json or "{}")
        except json.JSONDecodeError:
            return json.dumps(dict(schema=SCHEMA, ok=False, refused="payload_not_json",
                                   authority=AUTHORITY, admitted=False), sort_keys=True)
        return json.dumps(invoke_readonly(uri, payload), sort_keys=True, default=str)

    @server.tool()
    def kuhul_resolve_route(route_name: str) -> str:
        """Resolve a declared AIML/SRAI route name. Resolution only: no dispatch, no authority."""
        return json.dumps(resolve_route(route_name), sort_keys=True)

    @server.resource("kuhul://host/authority")
    def host_authority() -> str:
        """What this host refuses to do over MCP."""
        return json.dumps(dict(schema=SCHEMA, authority=AUTHORITY, execution=False, mutation=False,
                               admitted=False, effect_policy="read_only",
                               note=("tools cover registered read-only handlers only; a route is resolved, "
                                     "never dispatched; results grant nothing downstream")), sort_keys=True)

    @server.resource("kuhul://runtime/tree")
    def host_tree() -> str:
        return json.dumps(runtime_tree(), sort_keys=True, default=str)

    @server.resource("kuhul://phases/last")
    def host_phases() -> str:
        return json.dumps(last_phases(), sort_keys=True, default=str)

    return server, version


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Expose KTUI's read-only handlers over MCP.")
    parser.add_argument("--transport", default="stdio", choices=("stdio", "streamable-http", "sse"))
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--describe", action="store_true", help="print the surface and exit")
    args = parser.parse_args(argv)
    server, version = build_server()
    if args.describe:
        print(json.dumps(dict(schema=SCHEMA, sdk=version, server=SERVER_NAME, authority=AUTHORITY,
                              tools=["kuhul_list_handlers", "kuhul_invoke_readonly", "kuhul_resolve_route"],
                              resources=["kuhul://host/authority", "kuhul://runtime/tree",
                                         "kuhul://phases/last"]), indent=2))
        return 0
    if version == "v2":
        server.run(transport=args.transport)
    else:
        if args.transport == "streamable-http":
            server.settings.port = args.port
        server.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
