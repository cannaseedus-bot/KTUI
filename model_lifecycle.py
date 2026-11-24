"""Inference on demand: HOT when a backend is listening, COLD when it is not, and a registered wake.

The router selects a *healthy* endpoint; it does not start one. This module adds that missing step, with
the safety the review asked for:

    only a registered launcher runs        the manifest names the alias, the port and the flags; a
                                           proposal can never supply a command
    only an owned process is stopped       a process this lifecycle started (pid recorded, port matches);
                                           another backend on the same machine is left alone
    never stop while a lease is held       several micronauts can share one backend, so a stop needs zero
                                           active leases and an expired idle timer

The WARM state - server running with the model unloaded - is declared unavailable rather than faked:
`llama-server` in this build loads at start, so a backend is either listening (HOT) or not (COLD).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import model_router  # noqa: E402
import runtime_servers  # noqa: E402

SCHEMA = "kuhul-model-lifecycle/1"
STATES = ("hot", "warm", "cold", "unknown")
DEFAULTS = dict(idle_timeout_seconds=300, startup_timeout_seconds=180)


class LifecycleError(ValueError):
    """A launch or stop that the declaration does not permit."""


def load(path: Path | None = None) -> dict:
    """Read the lifecycle declarations, validating that every launch is host-registered."""
    source = Path(path or model_router.MANIFEST)
    router = model_router.load(source)
    problems = list(router["problems"])
    try:
        # The router keeps only what routing needs; the lifecycle fields are read from the same file.
        raw = json.loads(source.read_text(encoding="utf-8")).get("models") or {}
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, problems=problems + [dict(code="unreadable", detail=str(error))],
                    by_name={}, router=router, authority="declaration_only")
    models: dict[str, dict] = {}
    for name, entry in (router.get("models") or {}).items():
        declared = raw.get(name) or {}
        launch = declared.get("launch") or {}
        entry = dict(entry, state=declared.get("state"),
                     idle_timeout_seconds=declared.get("idle_timeout_seconds"),
                     startup_timeout_seconds=declared.get("startup_timeout_seconds"))
        alias = str(launch.get("alias") or "").strip()
        port = launch.get("port") or entry.get("port")
        if not alias:
            problems.append(dict(code="launch", detail=f"{name}: no registered launch alias"))
        if not isinstance(port, int):
            problems.append(dict(code="launch", detail=f"{name}: no registered launch port"))
        if launch.get("command"):
            # A command field is exactly what must never exist: the launcher is fixed.
            problems.append(dict(code="launch_command",
                                 detail=f"{name}: launches are declared, not commanded"))
        models[name] = dict(name=name, base_url=entry["base_url"], role=entry.get("role"),
                            features=list(entry.get("features") or []),
                            state=entry.get("state") or "cold",
                            idle_timeout_seconds=int(entry.get("idle_timeout_seconds")
                                                     or DEFAULTS["idle_timeout_seconds"]),
                            startup_timeout_seconds=int(entry.get("startup_timeout_seconds")
                                                        or DEFAULTS["startup_timeout_seconds"]),
                            launch=dict(alias=alias, port=port,
                                        no_think=bool(launch.get("no_think"))))
    return dict(ok=not problems, problems=problems, by_name=models,
                router=router, authority="declaration_only")


# -- the host's launcher, injectable so tests never spawn a server ---------------------------------------
def default_launcher() -> dict:
    """Launch through task-engine.py, which resolves the model from the registry - not from a string."""
    def launch(name: str, spec: dict) -> dict:
        argv = [sys.executable, str(HOST_ROOT / "task-engine.py"), "launch",
                "--model", spec["alias"], "--port", str(spec["port"])]
        if spec.get("no_think"):
            argv.append("--no-think")
        process = subprocess.Popen(argv, cwd=str(HOST_ROOT), stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, text=True)
        return dict(pid=process.pid, argv=argv, model=name)

    def stop(name: str, spec: dict) -> dict:
        return runtime_servers.stop(spec["port"])

    def listening(port: int) -> bool:
        return bool(runtime_servers.listeners(port))

    return dict(launch=launch, stop=stop, listening=listening, clock=time.monotonic)


def _host_call(host, name: str, *args):
    """The host may be the dict built here or any object with the same methods (tests, embedders)."""
    target = host[name] if isinstance(host, dict) else getattr(host, name)
    return target(*args)


def _listening(port: int, host) -> bool:
    return bool(_host_call(host, "listening", port))


def state(declaration: dict, name: str, *, host: dict | None = None) -> dict:
    """HOT when the declared port answers a listen check, COLD when it does not."""
    entry = (declaration.get("by_name") or {}).get(str(name))
    if entry is None:
        return dict(schema=SCHEMA, model=str(name), state="unknown", refused="model_not_registered")
    host = host or default_launcher()
    port = entry["launch"]["port"]
    hot = _listening(port, host)
    return dict(schema=SCHEMA, model=name, state="hot" if hot else "cold", port=port,
                base_url=entry["base_url"], declared=entry["state"],
                note="warm (model unloaded while serving) is not supported by this runtime",
                authority="declaration_only")


class Lifecycle:
    """Leases, ownership and the idle timer. One instance per process, deliberately."""

    def __init__(self, declaration: dict, *, host: dict | None = None):
        self.declaration = declaration
        self.host = host or default_launcher()
        self.leases: dict[str, int] = {}
        self.owned: dict[str, dict] = {}
        self.last_used: dict[str, float] = {}

    # -- leases ------------------------------------------------------------------------------------
    def acquire(self, name: str) -> dict:
        entry = self.declaration["by_name"].get(str(name))
        if entry is None:
            raise LifecycleError(f"{name!r} is not a registered model")
        self.leases[name] = self.leases.get(name, 0) + 1
        self.last_used[name] = _host_call(self.host, "clock")
        return dict(model=name, leases=self.leases[name], state=self.state_of(name))

    def release(self, name: str) -> dict:
        if not self.leases.get(name):
            raise LifecycleError(f"{name!r} has no active lease")
        self.leases[name] -= 1
        self.last_used[name] = _host_call(self.host, "clock")
        return dict(model=name, leases=self.leases[name])

    def state_of(self, name: str) -> str:
        return state(self.declaration, name, host=self.host)["state"]

    # -- wake --------------------------------------------------------------------------------------
    def ensure(self, name: str) -> dict:
        """Wake a COLD backend by the registered launcher; return at once if it is already HOT."""
        entry = self.declaration["by_name"].get(str(name))
        if entry is None:
            raise LifecycleError(f"{name!r} is not a registered model")
        port = entry["launch"]["port"]
        if _listening(port, self.host):
            return dict(schema=SCHEMA, model=name, state="hot", started=False, port=port,
                        note="already serving; nothing was launched")
        launched = _host_call(self.host, "launch", name, entry["launch"])
        # Startup is wall-clock time, not the injected idle clock: waiting on a fake clock that never
        # advances would spin forever, and a real launch takes real seconds.
        deadline = time.monotonic() + entry["startup_timeout_seconds"]
        while time.monotonic() < deadline:
            if _listening(port, self.host):
                self.owned[name] = dict(pid=launched.get("pid"), port=port,
                                        started_at=_host_call(self.host, "clock"))
                return dict(schema=SCHEMA, model=name, state="hot", started=True, port=port,
                            pid=launched.get("pid"))
            time.sleep(0.25)
        return dict(schema=SCHEMA, model=name, state="cold", started=True, port=port,
                    pid=launched.get("pid"), timeout=True,
                    note="launched, but the port never opened; the process was left for inspection")

    # -- sleep -------------------------------------------------------------------------------------
    def release_idle(self, *, now: float | None = None) -> dict:
        """Stop every backend that is owned, unleased and idle beyond its timeout."""
        now = _host_call(self.host, "clock") if now is None else now
        stopped, kept = [], []
        for name, record in list(self.owned.items()):
            entry = self.declaration["by_name"].get(name)
            if entry is None or self.leases.get(name):
                kept.append(dict(model=name, reason="leased" if self.leases.get(name) else "unregistered"))
                continue
            idle = now - self.last_used.get(name, record["started_at"])
            if idle < entry["idle_timeout_seconds"]:
                kept.append(dict(model=name, reason="not_idle",
                                 idle_seconds=int(idle), timeout=entry["idle_timeout_seconds"]))
                continue
            if not _listening(record["port"], self.host):
                self.owned.pop(name, None)
                stopped.append(dict(model=name, reason="already_stopped"))
                continue
            outcome = _host_call(self.host, "stop", name,
                                 dict(alias=entry["launch"]["alias"], port=record["port"]))
            self.owned.pop(name, None)
            stopped.append(dict(model=name, reason="idle", idle_seconds=int(idle),
                                result=outcome))
        return dict(schema=SCHEMA, stopped=stopped, kept=kept, owned=sorted(self.owned))


def summary(declaration: dict, *, host: dict | None = None) -> str:
    if not declaration["ok"]:
        lines = ["model lifecycle · INVALID"]
        lines += [f"  {problem['code']}: {problem['detail']}" for problem in declaration["problems"]]
        return "\n".join(lines)
    host = host or default_launcher()
    lines = [f"model lifecycle · {len(declaration['by_name'])} model(s) · {declaration['authority']}"]
    for name, entry in sorted(declaration["by_name"].items()):
        current = state(declaration, name, host=host)["state"]
        lines.append(f"  {name:8} declared {entry['state']:5} now {current:5} "
                     f"port {entry['launch']['port']} · idle {entry['idle_timeout_seconds']}s")
    lines.append("  (only a registered launch can wake a model; only an owned, unleased process sleeps)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Model lifecycle: state, wake, or sleep one backend.")
    parser.add_argument("action", choices=("state", "wake", "sleep"), nargs="?", default="state")
    parser.add_argument("model", nargs="?")
    args = parser.parse_args(argv)
    declaration = load()
    host = default_launcher()
    lifecycle = Lifecycle(declaration, host=host)
    if args.action == "state":
        print(summary(declaration, host=host))
        return 0
    if not args.model:
        print("a model name is required for wake and sleep")
        return 2
    if args.action == "wake":
        print(json.dumps(lifecycle.ensure(args.model), indent=2))
        return 0
    print(json.dumps(lifecycle.release_idle(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

def observed(lifecycle: "Lifecycle") -> dict:
    """What the green screen may display: leases, ownership and idle budget - read, never acted on."""
    view = {}
    now = _host_call(lifecycle.host, "clock")
    for name, entry in lifecycle.declaration["by_name"].items():
        record = lifecycle.owned.get(name)
        leases = lifecycle.leases.get(name, 0)
        last = lifecycle.last_used.get(name) or (record or {}).get("started_at")
        remaining = None
        if record and last is not None and not leases:
            remaining = max(0, int(entry["idle_timeout_seconds"] - (now - last)))
        view[name] = dict(leases=leases, owned=bool(record),
                          idle_remaining=("suspended" if leases else remaining))
    return view

