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
                                            "GET /v1/phases", "GET /v1/identity"],
                                 uri=uri(), transport=transport()))
        else:
            self._send(404, dict(error="unknown path", path=route))

    def do_POST(self) -> None:
        route = self._path()
        if route not in ("/v1/chat", "/chat"):
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


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Serve the daemon on loopback (micronaut://v1/chat).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default=DEFAULT_HOST)
    args = parser.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"warning: binding {args.host} exposes the endpoint beyond loopback", flush=True)
    print(f"{uri()}  ->  {transport(args.port)}", flush=True)
    serve(args.port, args.host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
