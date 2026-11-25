"""A reachable local endpoint for the daemon: `micronaut://v1/chat` over HTTP on loopback.

The scheme is logical - `micronaut://v1/chat` is `http://127.0.0.1:<port>/v1/chat` - because nothing
outside this process resolves a custom scheme. Saying so plainly is better than shipping a URI that
does not work.

What the endpoint will do: answer from the local pipeline (AIML, the daemon's six phases, memory
reads, identity, git reads). What it will *not* do: call the model, write memory, commit, push, clone
or write files. A network client has no grant and no way to obtain one, so a request that would need
one comes back as `refused` with the reason, and a request the local layer cannot answer comes back as
`deferred` - the model is never invoked on someone else's behalf.

    POST /v1/chat        {"message": "who are you"}   -> {"kind": "aiml", "reply": "...", "phases": [...]}
    GET  /v1/health                                    -> {"ok": true, "model": "...", "uptime_s": 12.3}
    GET  /v1/models                                    -> {"models": ["gemma-3-1b", ...], "default": "..."}
    GET  /v1/phases                                    -> the six-phase trace of the last turn
    GET  /v1/identity                                  -> the daemon's self-description (plain text)
    POST /api/atomic/call {"key":"graph-theory.query","query":{"operation":"inventory"}}
                                                              -> bounded, read-only GML query proposal

Loopback only: the server binds 127.0.0.1 and refuses to start on a routable address unless the caller
insists, which is a deliberate speed bump rather than a security boundary.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = 8756
DEFAULT_HOST = "127.0.0.1"
SCHEME = "micronaut"
MAX_BODY = 64 * 1024


def uri(port: int = DEFAULT_PORT, method: str = "v1/chat") -> str:
    """The logical address, and the transport it actually maps to."""
    return f"{SCHEME}://{method.strip('/')}"


def transport(port: int = DEFAULT_PORT, method: str = "v1/chat") -> str:
    return f"http://{DEFAULT_HOST}:{port}/{method.strip('/')}"


class Engine:
    """The local pipeline, without a TUI. One instance, used from the request threads."""

    def __init__(self, app=None):
        import chat_app

        self.app = app or chat_app.ChatApp()
        self.started = time.monotonic()
        self.lock = threading.Lock()

    def capabilities(self) -> set:
        """What this host may do in route terms: its grants, plus the read capabilities it always has."""
        granted = {"graph.relations.read"}
        app = getattr(self, "app", None)
        if app is not None and hasattr(app, "granted_capabilities"):
            try:
                granted |= set(app.granted_capabilities())
            except Exception:
                pass
        return granted

    def invoke_micronaut(self, uri: str, payload: dict, *, from_uri: str | None = None) -> dict:
        """Invoke one registered read-only handler through host admission.

        Identity and capabilities come from this Engine's session; payload fields cannot assert them.
        This method deliberately is not exposed as an unauthenticated HTTP route.
        """
        import micronaut_host_handlers

        app = self.app
        identity = str(getattr(app, "user_id", "") or "").strip()
        if not identity:
            raise micronaut_host_handlers.HandlerRefused("host_identity_unavailable")
        granted = self.capabilities()

        def host_policy(binding, _payload):
            return (binding.effect == "read_only" and binding.capability in granted and
                    binding.uri in micronaut_host_handlers.bindings())

        host = micronaut_host_handlers.HandlerHost(identity=identity, granted=granted,
                                                   policy=host_policy)
        admission = host.admit(uri, payload, from_uri=from_uri)
        with self.lock:  # AIML phase resolution holds shared per-process matching state
            result = host.invoke(admission, payload)
            self.last_micronaut_invocation = host.invocations[-1]
        return result

    def invoke_gml_filter_map(self, payload: dict) -> dict:
        """Run the first typed GML edge through one host and one Engine-owned request lock."""
        import micronaut_host_handlers

        contract = micronaut_host_handlers.gml_chain_contract()
        if not contract["validation"]["ok"]:
            raise micronaut_host_handlers.HandlerRefused("gml_edge_validation_failed")
        identity = str(getattr(self.app, "user_id", "") or "").strip()
        if not identity:
            raise micronaut_host_handlers.HandlerRefused("host_identity_unavailable")
        granted = self.capabilities()

        def host_policy(binding, _payload):
            return (binding.effect == "read_only" and binding.capability in granted and
                    binding.uri in micronaut_host_handlers.bindings())

        host = micronaut_host_handlers.HandlerHost(identity=identity, granted=granted,
                                                   policy=host_policy)
        try:
            with self.lock:
                filtered_ticket = host.admit(micronaut_host_handlers.GML_FILTER_URI, payload)
                filtered = host.invoke(filtered_ticket, payload)
                filtered_payload = filtered["payload"]
                mapped_ticket = host.admit(
                    micronaut_host_handlers.GML_MAP_URI,
                    filtered_payload,
                    from_uri=micronaut_host_handlers.GML_FILTER_URI,
                )
                mapped = host.invoke(mapped_ticket, filtered_payload)
                self.last_micronaut_invocation = host.invocations[-1]
        except Exception as error:
            return {
                "$schema": "kuhul://schema/gml-chain-result/v1",
                "chain": "filter_to_map",
                "status": "REJECTED",
                "typed_edge": contract,
                "phases": [
                    {"phase": "Ch'en", "status": "REJECTED",
                     "reason": f"{type(error).__name__}: {error}"},
                    {"phase": "Xul", "status": "NOT_CLOSED"},
                ],
                "invocations": list(host.invocations),
                "authority": "host_read_only",
                "admitted": False,
                "effects": dict(tool_dispatch=False, mutation=False, persistence=False),
            }
        return {
            "$schema": "kuhul://schema/gml-chain-result/v1",
            "chain": "filter_to_map",
            "status": "VERIFIED_READ_RESULT",
            "typed_edge": contract,
            "payload": mapped["payload"],
            "phases": [
                {"phase": "Sek", "status": "DISPATCHED", "operators": ["filter", "map"]},
                {"phase": "Ch'en", "status": "VERIFIED", "edge": contract["edge"]},
                {"phase": "Xul", "status": "CLOSED"},
            ],
            "invocations": list(host.invocations),
            "engine_reused": True,
            "authority": "host_read_only",
            "admitted": True,
            "effects": dict(tool_dispatch=False, mutation=False, persistence=False),
        }

    def graph_query(self, payload: dict) -> dict:
        """Read an allowlisted repository GML graph and return a DATA_ONLY proposal."""
        import micronaut_host_handlers

        granted = self.capabilities()

        def host_policy(binding, _query):
            return (binding.uri == "micronaut:GRAPH-THEORY" and
                    binding.handler_id == "micronaut.graph_executor.execute_graph_query" and
                    binding.capability == "read_graph_inventory" and
                    binding.effect == "read_only" and "graph.relations.read" in granted)

        host = micronaut_host_handlers.GraphTheoryHost(policy=host_policy)
        with self.lock:
            result = host.invoke(payload)
            self.last_graph_invocation = host.invocations[-1]
        return result

    def graph_health(self) -> dict:
        import micronaut_host_handlers
        binding = micronaut_host_handlers.GRAPH_THEORY_BINDING
        return dict(ok=True, micronaut=binding.uri, handler=binding.handler_id,
                    input_schema=binding.input_schema, output_schema=binding.output_schema,
                    effects=dict(tool_dispatch=False, mutation=False, persistence=False))

    def _trace(self) -> list[dict]:
        turn = getattr(self.app, "last_turn", None)
        return [dict(phase=name, detail=detail) for name, detail in (turn.phases if turn else [])]

    def chat(self, message: str) -> dict:
        message = (message or "").strip()
        if not message:
            return dict(kind="error", reply="an empty message has nothing to answer", phases=[])
        with self.lock:  # the pipeline keeps last_turn; requests must not interleave
            outcome = self.app.local_answer(message)
        if outcome is None:
            return dict(kind="deferred", reply=None, phases=self._trace(),
                        note="no local answer - the model is not invoked over the network")
        kind, reply = outcome
        references = []
        try:
            import links
            if kind in ("aiml", "deferred"):
                references = links.for_text(message)
        except ImportError:
            references = []
        return dict(kind=kind, reply=str(reply), phases=self._trace(), links=references)

    def health(self) -> dict:
        app = self.app
        return dict(ok=True, model=app.model_label(), provider=app.current_provider.value,
                    mode=getattr(app, "mode", ""), uptime_s=round(time.monotonic() - self.started, 1),
                    workspace=str(getattr(getattr(app, "sandbox", None), "root", APP_ROOT)),
                    writes=bool(getattr(getattr(app, "sandbox", None), "allow_write", False)),
                    phases=["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"],
                    uri=uri(), transport=transport())

    def models(self) -> dict:
        import chat_app
        return dict(models=list(chat_app.MODEL_REGISTRY), default=chat_app.DEFAULT_MODEL_ALIAS)


class Handler(BaseHTTPRequestHandler):
    server_version = "MicronautDaemon/1"
    engine: Engine = None  # set by serve()

    # -- plumbing -------------------------------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:  # keep the TUI's terminal clean
        return

    def _send(self, status: int, payload: dict, *, text: bool = False) -> None:
        body = (payload if text else json.dumps(payload, ensure_ascii=False)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8" if text else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _path(self) -> str:
        return urlparse(self.path).path.rstrip("/") or "/"

    def _query(self) -> dict:
        return {key: values[-1] for key, values in parse_qs(urlparse(self.path).query).items()}

    # -- routes ---------------------------------------------------------------------------------
    def do_GET(self) -> None:
        route = self._path()
        if route == "/api/health":
            self._send(200, self.engine.graph_health())
            return
        if route.startswith("/api/"):
            # kuhul-rest/v1: the manifest decides the route, this host serves it read-only.
            try:
                import rest_adapter
                query = self._query()
                if "as" in query:
                    # Identity comes from the transport, never from the request's own text.
                    self._send(400, dict(error="identity may not be asserted in the query; use the "
                                                "Authorization header"))
                    return
                grant = self.headers.get("Authorization") or ""
                token = grant.split(" ", 1)[1].strip() if grant.lower().startswith("bearer ") else ""
                granted = set(self.engine.capabilities()) if hasattr(self.engine, "capabilities") else set()
                result = rest_adapter.handle("GET", self.path, token=token, granted=granted)
            except Exception as error:  # a broken adapter is a 500, not a dropped connection
                self._send(500, dict(error=f"{type(error).__name__}: {error}"))
                return
            self._send(result["status"], result)
            return
        if route in ("/v1/health", "/health"):
            self._send(200, self.engine.health())
        elif route in ("/v1/models", "/models"):
            self._send(200, self.engine.models())
        elif route in ("/v1/phases", "/phases"):
            self._send(200, dict(phases=self.engine._trace()))
        elif route in ("/v1/identity", "/identity"):
            self._send(200, self.engine.app.identity_text(), text=True)
        elif route in ("/", "/v1"):
            self._send(200, dict(endpoints=["POST /v1/chat", "GET /v1/health", "GET /v1/models",
                                            "GET /v1/phases", "GET /v1/identity",
                                            "POST /v1/graph/query"],
                                 uri=uri(), transport=transport()))
        else:
            self._send(404, dict(error="unknown path", path=route))

    def do_POST(self) -> None:
        route = self._path()
        if route not in ("/v1/chat", "/chat", "/v1/graph/query", "/api/atomic/call"):
            self._send(404, dict(error="unknown path", path=route))
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, dict(error="bad Content-Length"))
            return
        if length > MAX_BODY:
            self._send(413, dict(error=f"body larger than {MAX_BODY} bytes"))
            return
        raw = self.rfile.read(length) if length else b""
        message = ""
        if raw:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(400, dict(error="body must be JSON"))
                return
            if isinstance(payload, dict):
                message = str(payload.get("message") or "")
            elif isinstance(payload, str):
                message = payload
        if route in ("/v1/graph/query", "/api/atomic/call"):
            if not isinstance(locals().get("payload"), dict):
                self._send(400, dict(error="body must be a JSON object with a query"))
                return
            if route == "/api/atomic/call":
                key = payload.get("key")
                if key not in ("graph-theory.query", "graph-theory.match"):
                    self._send(404, dict(error="unregistered atomic key"))
                    return
                query = payload.get("query")
                if not isinstance(query, dict):
                    self._send(400, dict(error="query must be an object"))
                    return
                expected_op = "match" if key == "graph-theory.match" else None
                if expected_op and query.get("operation") != expected_op:
                    self._send(400, dict(error="graph-theory.match requires operation=match"))
                    return
                payload = {"$schema": "kuhul://schema/graph-query/v1", "query": query}
            try:
                result = self.engine.graph_query(payload)
            except Exception as error:
                import micronaut_host_handlers
                import micronaut.graph_executor as graph_executor
                status = 403 if isinstance(error, micronaut_host_handlers.HandlerRefused) else 400 \
                    if isinstance(error, graph_executor.GraphQueryError) else 500
                self._send(status, dict(error=f"{type(error).__name__}: {error}"))
                return
            self._send(200, result)
            return
        if not message:
            message = self._query().get("message", "")
        if not message:
            self._send(400, dict(error="a message is required", uri=uri(),
                                 example={"message": "who are you"}))
            return
        self._send(200, self.engine.chat(message))

    def do_PUT(self) -> None:
        self._send(405, dict(error="method not allowed", allowed=["GET", "POST"]))

    do_DELETE = do_PUT
    do_PATCH = do_PUT


def serve(port: int = DEFAULT_PORT, host: str = DEFAULT_HOST, *, engine: Engine | None = None,
          block: bool = True) -> ThreadingHTTPServer:
    """Start the endpoint. `block=False` returns the server so a caller can thread it."""
    engine = engine or Engine()
    handler = type("BoundHandler", (Handler,), dict(engine=engine))
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    if block:
        server.serve_forever()
    return server


def start_mcp(port: int, host: str = DEFAULT_HOST) -> dict:
    """Serve the MCP surface from this same process, on its own listener.

    This server is a stdlib ThreadingHTTPServer, and the MCP SDK's streamable transport is an ASGI app. Rather than
    rewrite the HTTP layer, the ASGI app runs in a daemon thread beside it - one process, one command, two listeners,
    and neither framework pretending to be the other.
    """
    import threading

    import uvicorn

    import mcp_host

    server, version = mcp_host.build_server()
    application = server.streamable_http_app()
    config = uvicorn.Config(application, host=host, port=int(port), log_level="warning")
    http = uvicorn.Server(config)
    http.install_signal_handlers = lambda: None          # the main thread owns the signals
    thread = threading.Thread(target=http.run, name="mcp-host", daemon=True)
    thread.start()
    return dict(url=f"http://{host}:{int(port)}/mcp", sdk=version, thread=thread, server=http)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Serve the daemon on loopback (micronaut://v1/chat).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--mcp-port", type=int, default=0,
                        help="also serve the MCP surface on this port (0 or unset disables it)")
    args = parser.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"warning: binding {args.host} exposes the endpoint beyond loopback", flush=True)
    print(f"{uri()}  ->  {transport(args.port)}", flush=True)
    if args.mcp_port:
        try:
            started = start_mcp(args.mcp_port, args.host)
            print(f"mcp        ->  {started['url']}  (sdk {started['sdk']}, read-only surface)", flush=True)
        except Exception as error:                       # a missing MCP dependency must not stop the daemon
            print(f"mcp        ->  unavailable: {type(error).__name__}: {error}", flush=True)
    serve(args.port, args.host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
