"""Commit, push and build the repository on command - with git's own words when it fails.

The rule this module keeps: an operation either returns real output or the real error. There is no
"✓ pushed" unless git said so, and no invented commit message. Every function returns

    {"ok": bool, "command": [argv], "exit_code": int | None, "output": str}

so the caller can show exactly what ran and exactly what came back.

Authority: nothing here is reachable from the model's tool surface. The sandbox's git allowlist stays
read-only (status/diff/log/...), and these operations run only from a host command with an explicit
grant - the same shape as memory writes.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
DEFAULT_MESSAGE = "checkpoint: {count} file(s) changed"


def run(args: list[str], cwd: Path | str = APP_ROOT, *, timeout: int = 180) -> dict:
    """Run one command, keep both streams, and never raise for a non-zero exit."""
    argv = [str(item) for item in args]
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, shell=False,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except FileNotFoundError as error:
        return dict(ok=False, command=argv, exit_code=None, output=f"{argv[0]} not found: {error}")
    except subprocess.TimeoutExpired:
        return dict(ok=False, command=argv, exit_code=None,
                    output=f"timed out after {timeout}s: {' '.join(argv)}")
    out = ((proc.stdout or "").strip() or (proc.stderr or "").strip()
           or f"(no output · exit {proc.returncode})")
    return dict(ok=proc.returncode == 0, command=argv, exit_code=proc.returncode, output=out[:4000],
                stdout=(proc.stdout or "").strip(), stderr=(proc.stderr or "").strip())


def status(root: Path = APP_ROOT, *, runner=run) -> dict:
    result = runner(["git", "status", "--porcelain"], root)
    changed = [line[3:].strip() for line in result["output"].splitlines()
               if line.strip() and not line.startswith("(no output")]
    if not result["ok"]:
        return dict(result, dirty=False, changed=[])
    return dict(result, dirty=bool(changed), changed=changed)


def branch(root: Path = APP_ROOT, *, runner=run) -> str | None:
    result = runner(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)
    return result["output"].strip() if result["ok"] else None


def build(root: Path = APP_ROOT, *, runner=run) -> dict:
    """Compile every tracked Python file, then run the package suite. Real steps, real output."""
    steps = []
    files = runner(["git", "ls-files", "*.py"], root)
    if not files["ok"]:
        return dict(ok=False, steps=[files], output=files["output"], command=files["command"],
                    exit_code=files["exit_code"])
    targets = [name for name in files["output"].splitlines() if name.endswith(".py")]
    compile_step = runner([sys.executable, "-m", "compileall", "-q", *targets], root) if targets else \
        dict(ok=True, command=[sys.executable, "-m", "compileall"], exit_code=0,
             output="(no tracked Python files)", stdout="", stderr="")
    steps.append(compile_step)
    package = Path(root) / "kuhul-phase-engine-v0.1.0"
    if package.is_dir():
        steps.append(runner([sys.executable, "-m", "unittest", "discover", "-s", "tests"], package))
    ok = all(step["ok"] for step in steps)
    failed = next((step for step in steps if not step["ok"]), None)
    return dict(ok=ok, steps=steps, command=(failed or steps[-1])["command"],
                exit_code=(failed or steps[-1])["exit_code"],
                output="\n\n".join(f"$ {' '.join(step['command'])}\n{step['output']}" for step in steps))


def commit(root: Path = APP_ROOT, message: str = "", *, add_all: bool = True, runner=run) -> dict:
    """Stage and commit. Refuses to invent a commit when there is nothing to commit."""
    state = status(root, runner=runner)
    if not state["ok"]:
        return dict(state, ok=False, output=f"cannot read the working tree:\n{state['output']}")
    if not state["dirty"]:
        return dict(ok=False, command=["git", "commit"], exit_code=None,
                    output="nothing to commit - the working tree is clean", changed=[], steps=[])
    steps = []
    if add_all:
        steps.append(runner(["git", "add", "-A"], root))
    text = (message or "").strip() or DEFAULT_MESSAGE.format(count=len(state["changed"]))
    steps.append(runner(["git", "commit", "-m", text], root))
    failed = next((step for step in steps if not step["ok"]), None)
    return dict(ok=failed is None, command=(failed or steps[-1])["command"],
                exit_code=(failed or steps[-1])["exit_code"],
                output="\n\n".join(f"$ {' '.join(step['command'])}\n{step['output']}" for step in steps),
                message=text, changed=state["changed"], steps=steps)


def _github_token() -> str | None:
    """The token `gh` already holds, when it is available. Never printed."""
    gh = shutil.which("gh")
    if not gh:
        return None
    result = run([gh, "auth", "token"], APP_ROOT, timeout=30)
    token = result["output"].strip()
    return token if result["ok"] and token and " " not in token else None


def push(root: Path = APP_ROOT, *, remote: str = "origin", branch_name: str | None = None,
         runner=run, token_provider=_github_token) -> dict:
    """Push, trying the authenticated form first, then the plain one. Returns git's own failure."""
    target = branch_name or branch(root, runner=runner)
    if not target:
        return dict(ok=False, command=["git", "push"], exit_code=None,
                    output="cannot push: the current branch could not be determined")
    attempts = []
    token = token_provider()
    if token:
        auth = base64.b64encode(f"x-access-token:{token}".encode("ascii")).decode("ascii")
        attempts.append(runner(["git", "-c", "credential.helper=",
                             "-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {auth}",
                              "push", remote, target], root, timeout=300))
    attempts.append(runner(["git", "push", remote, target], root, timeout=300))
    success = next((attempt for attempt in attempts if attempt["ok"]), None)
    chosen = success or attempts[-1]
    header = "" if success or len(attempts) == 1 else \
        f"({len(attempts)} attempt(s); showing the last error)\n\n"
    return dict(chosen, branch=target, remote=remote, output=header + chosen["output"][:4000],
                attempts=[dict(ok=attempt["ok"], exit_code=attempt["exit_code"],
                               output=attempt["output"][:400] if not attempt["ok"] else "(succeeded)")
                          for attempt in attempts])


def sync(root: Path = APP_ROOT, message: str = "", *, runner=run) -> dict:
    """Commit, then push. Stops at the first real failure and reports it."""
    committed = commit(root, message, runner=runner)
    if not committed["ok"]:
        return dict(ok=False, stage="commit", commit=committed, output=committed["output"],
                    command=committed.get("command"), exit_code=committed.get("exit_code"))
    pushed = push(root, runner=runner)
    return dict(ok=pushed["ok"], stage="push" if not pushed["ok"] else "done",
                commit=committed, push=pushed,
                output=f"{committed['output']}\n\n{pushed['output']}",
                command=pushed.get("command"), exit_code=pushed.get("exit_code"))
