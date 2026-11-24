"""One real idle transition: a lifecycle-owned server is started, leased, released, and stopped by the sweep.

This is an observation, not a unit test: it spawns a real llama-server on a spare port through the registered
launcher, waits out a short idle budget, and records what actually happened - the stop event, the process exit,
the resulting state, and whether a lease held during the window prevents shutdown.

The point of running it here rather than mocking: the projection has only ever reported COLD from a fake host, so
"HOT -> COLD" is until now a tested mechanism and not an observed behaviour.
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

import model_lifecycle  # noqa: E402
import runtime_servers  # noqa: E402

SCHEMA = "kuhul://lifecycle/transition-observation/v1"
ALIAS = "gemma-3-1b"
PORT = 9042
IDLE_SECONDS = 8


def _declaration(idle: int) -> dict:
    """The shipped declaration with a short idle budget and a spare port for this observation."""
    record = json.loads((PACKAGE / "data" / "models.json").read_text(encoding="utf-8"))
    record["models"]["worker"]["launch"]["port"] = PORT
    record["models"]["worker"]["idle_timeout_seconds"] = idle
    folder = HOST_ROOT / "logs" / "lifecycle-observation.json"
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return model_lifecycle.load(folder)


def _pid_on(port: int) -> list[int]:
    return [item["pid"] for item in runtime_servers.listeners(port)]


def observe() -> dict:
    started = time.monotonic()
    declaration = _declaration(IDLE_SECONDS)
    lifecycle = model_lifecycle.Lifecycle(declaration)
    steps = []

    def note(step: str, **detail) -> None:
        steps.append(dict(step=step, at_ms=int(round((time.monotonic() - started) * 1000)), **detail))

    before = lifecycle.state_of("worker")
    note("before", state=before, listening=_pid_on(PORT))
    if before == "hot":
        return dict(schema=SCHEMA, ok=False, refused="port_already_in_use", port=PORT, steps=steps)

    wake_started = time.monotonic()
    woke = lifecycle.ensure("worker")
    wake_ms = int(round((time.monotonic() - wake_started) * 1000))
    note("wake", state=woke.get("state"), started=woke.get("started"), wake_ms=wake_ms,
         listening=_pid_on(PORT))
    if woke.get("state") != "hot":
        return dict(schema=SCHEMA, ok=False, refused="wake_failed", detail=woke, steps=steps)

    lease = lifecycle.acquire("worker")
    note("lease", leases=lease["leases"])
    # a sweep while leased must not stop it
    held = lifecycle.release_idle()
    note("sweep_while_leased", stopped=held["stopped"], kept=held["kept"], state=lifecycle.state_of("worker"))
    released = lifecycle.release("worker")
    note("release", leases=released["leases"])
    released_at = time.monotonic()

    # wait out the idle budget, then sweep
    deadline = released_at + IDLE_SECONDS + 1
    while time.monotonic() < deadline:
        time.sleep(0.25)
    idle_ms = int(round((time.monotonic() - released_at) * 1000))
    sweep_started = time.monotonic()
    sweep = lifecycle.release_idle()
    stop_ms = int(round((time.monotonic() - sweep_started) * 1000))
    note("sweep_after_idle", idle_ms=idle_ms, stop_ms=stop_ms, stopped=sweep["stopped"],
         kept=sweep["kept"], owned=sweep["owned"])

    # give the OS a moment to close the socket, then look
    for _ in range(40):
        if not _pid_on(PORT):
            break
        time.sleep(0.25)
    after = lifecycle.state_of("worker")
    note("after", state=after, listening=_pid_on(PORT))
    swept = [item for item in sweep["stopped"] if item.get("reason") == "idle"]
    already = [item for item in sweep["stopped"] if item.get("reason") == "already_stopped"]
    return dict(schema=SCHEMA, ok=bool(swept) and after == "cold" and not _pid_on(PORT),
                sweep_stopped_it=bool(swept), already_stopped=bool(already),
                refused=None if swept else "the server exited before the sweep could stop it",
                alias=ALIAS, port=PORT, idle_seconds=IDLE_SECONDS,
                wake_ms=wake_ms, stop_ms=stop_ms,
                stopped=sweep["stopped"], before_states=before, after_state=after,
                steps=steps, authority="declaration_only", execution=False,
                note=("one real observation: a lifecycle-owned server woken, leased, released and stopped by "
                      "the sweep after its idle budget"))


def summary(report: dict) -> str:
    state = "OBSERVED" if report.get("ok") else "NOT OBSERVED"
    lines = [f"idle transition · {state} · port {report.get('port')} · idle {report.get('idle_seconds')}s"]
    for step in report.get("steps") or []:
        detail = {key: value for key, value in step.items() if key not in ("step", "at_ms")}
        lines.append(f"  {step['at_ms']:>6} ms  {step['step']:18} {detail}")
    if report.get("refused"):
        lines.append(f"  refused: {report['refused']} {report.get('detail', '')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    out = Path(argv[0]) if argv else PACKAGE / "data" / "lifecycle-transition.json"
    report = observe()
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(summary(report))
    print(f"written: {out}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
