"""Port-scoped control of the llama-server instances: stop one backend without killing the other.

`taskkill /im llama-server.exe` stops every server on the machine - the advisor included. These helpers
find the process **listening on a port** and stop only that one, which is what the two-backend setup needs.

Windows gives two routes: `psutil` when it is installed, otherwise the `netstat -ano` table. Both are read
only; `stop()` is the single operation that terminates anything, and it terminates exactly one PID.
"""
from __future__ import annotations

import re
import subprocess
import sys

NETSTAT = re.compile(r"^\s*TCP\s+127\.0\.0\.1:(?P<port>\d+)\s+\S+\s+LISTENING\s+(?P<pid>\d+)\s*$",
                     re.M)


def _psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def listeners(port: int) -> list[dict]:
    """Processes listening on `port`, with the PID that owns each socket."""
    port = int(port)
    psutil = _psutil()
    if psutil is not None:
        found = []
        for connection in psutil.net_connections(kind="tcp"):
            if connection.status != psutil.CONN_LISTEN or not connection.laddr:
                continue
            if int(connection.laddr.port) != port:
                continue
            name = ""
            if connection.pid:
                try:
                    name = psutil.Process(connection.pid).name()
                except Exception:
                    name = ""
            found.append(dict(port=port, pid=connection.pid, name=name))
        return found
    try:
        table = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=15,
                               encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [dict(port=port, pid=int(match.group("pid")), name="(netstat)")
            for match in NETSTAT.finditer(table) if int(match.group("port")) == port]


def describe(port: int) -> dict:
    found = listeners(port)
    return dict(port=int(port), listening=bool(found), pids=[item["pid"] for item in found],
                processes=[item["name"] for item in found])


def stop(port: int) -> dict:
    """Stop the process listening on one port. Never a pattern kill, never another backend."""
    found = listeners(port)
    if not found:
        return dict(port=int(port), stopped=False, refused="nothing_listening",
                    reason="no process is listening on that port")
    pids = sorted({item["pid"] for item in found if item["pid"]})
    if not pids:
        return dict(port=int(port), stopped=False, refused="no_pid",
                    reason="a listener was found but its pid could not be read")
    psutil = _psutil()
    stopped, errors = [], []
    for pid in pids:
        try:
            if psutil is not None:
                process = psutil.Process(pid)
                process.terminate()
                process.wait(timeout=15)
            else:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                               timeout=15, text=True)
            stopped.append(pid)
        except Exception as error:
            errors.append(dict(pid=pid, error=f"{type(error).__name__}: {error}"[:160]))
    return dict(port=int(port), stopped=bool(stopped) and not errors, pids=pids,
                stopped_pids=stopped, errors=errors)


def summary(report: dict) -> str:
    if "listening" in report:
        state = "listening" if report["listening"] else "nothing listening"
        pids = ", ".join(str(pid) for pid in report["pids"]) or "-"
        return f"127.0.0.1:{report['port']} · {state} · pid(s) {pids}"
    if report.get("stopped"):
        return f"127.0.0.1:{report['port']} · stopped pid(s) {report['stopped_pids']}"
    return f"127.0.0.1:{report['port']} · not stopped: {report.get('refused') or report.get('errors')}"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Inspect or stop the llama-server on one port.")
    parser.add_argument("port", type=int)
    parser.add_argument("--stop", action="store_true", help="terminate only the process on that port")
    args = parser.parse_args(argv)
    report = stop(args.port) if args.stop else describe(args.port)
    print(summary(report))
    return 0 if (report.get("listening") or report.get("stopped")) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
