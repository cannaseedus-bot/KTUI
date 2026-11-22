"""gpt-oss terminal: a sandboxed command terminal the local model drives over llama-server's REST API.

The model talks ChatML/OpenAI-style messages and asks for tools; this process decides what a tool may
actually do. Two rules carry the whole design:

  1. The model never types into a shell. There is no shell. `run_command` takes a program name plus an
     argument list, the program must be on an allowlist, its subcommands are checked, and it runs with
     `shell=False` inside the sandbox root.
  2. The sandbox is the repository. Every path is resolved (so symlinks cannot escape), must stay
     under the root, and must not touch a blocked part (.git, node_modules, dist, logs, .env*). Writes
     are refused unless a human passed --allow-write, and the environment handed to a child process is
     scrubbed of everything but PATH.

Usage:
    python patches/task-engine.py status
    python patches/task-engine.py tools
    python patches/task-engine.py chat "why does the build fail?" --allow-write
    python patches/task-engine.py shell

A transcript of every task is appended to logs/gpt-oss-terminal/<stamp>.jsonl (logs/ is gitignored).

Tool calls arrive either as OpenAI `tool_calls` (the path llama-server uses when the chat template
supports tools) or, as a fallback, as a fenced json block in the content, which is how a template
without native tool support tends to answer. Both are parsed here; neither is trusted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:  # the task list the chat app renders, updated through AIML commands
    from task_list import apply as apply_task_command, render_text as render_tasks
except ImportError:  # pragma: no cover - the terminal still works without it
    apply_task_command = None
    render_tasks = None

try:  # one shared interaction log, so every local client's conversations can be compiled to AIML
    from interaction_log import log_interaction
except ImportError:  # pragma: no cover - the terminal still works without the dumper
    def log_interaction(**kwargs):  # type: ignore[misc]
        return None

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - older interpreters
    tomllib = None

CONFIG_PATH = Path(__file__).resolve().parent / "gpt-oss.toml"

# Programs the model may run. Read-only by character: nothing here writes to the repository except
# `git` subcommands that are themselves checked, and nothing reaches the network.
ALLOWED_PROGRAMS = {
    "git": {"status", "diff", "log", "show", "ls-files", "rev-parse", "branch", "grep", "describe"},
    "python": {"-c", "-m", "-V", "--version"},
    "python3": {"-c", "-m", "-V", "--version"},
    "node": {"-e", "-v", "--version", "-p", "--print"},
    "npm": {"ls", "run", "--version"},
    "npx": {"--version"},
    "pytest": {"--version", "-q", "--collect-only"},
}

# Flags that turn a read-only program into a writer or let it load foreign code. `-c` is denied for
# git only (it injects config); python and node use `-c` to evaluate, and their subcommand allowlist
# is what covers that. Comparison is by flag name, so `--output=file` is caught as `--output`.
DENIED_FLAGS = {
    "--output",
    "-o",
    "--exec-path",
    "--upload-pack",
    "--receive-pack",
    "--git-dir",
    "--work-tree",
    "--no-verify",
    "--config",
}
DENIED_GIT_FLAGS = {"-c"}

DENIED_PROGRAMS = {
    "rm", "rmdir", "del", "erase", "format", "mkfs", "dd", "shutdown", "reboot",
    "curl", "wget", "ssh", "scp", "ftp", "nc", "telnet", "powershell", "pwsh",
    "cmd", "sh", "bash", "zsh", "sudo", "runas", "taskkill", "reg", "sc",
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run one allowlisted program inside the repository sandbox. argv only: no shell, no pipes, no redirection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "program": {"type": "string", "description": "Program name, e.g. git, python, node, npm."},
                    "args": {"type": "array", "items": {"type": "string"}, "description": "Arguments, one per element."},
                },
                "required": ["program", "args"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List one directory inside the sandbox.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative path, default '.'."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file inside the sandbox, optionally a slice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "description": "1-based first line."},
                    "limit": {"type": "integer", "description": "Maximum lines to return."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Regex search over text files inside the sandbox; returns path:line:text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "description": "Directory to search, default '.'."},
                    "glob": {"type": "string", "description": "Optional filename glob, e.g. *.jsx."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_list",
            "description": "Maintain the shared task list the chat app renders. Actions: add, done, start, block, unblock, remove, list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "done", "start", "block", "unblock", "remove", "list"]},
                    "task": {"type": "string", "description": "Task title (add) or the id/title fragment (everything else)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a text file inside the sandbox. Refused unless the human enabled writes.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are gpt-oss working inside a KNUMATIC repository through a sandboxed terminal.

You have tools: run_command, list_dir, read_file, search, write_file. Use them to look before you
claim: read the file, run the command, then answer from what you saw.

Rules:
- One command per tool call, argv only. No pipes, redirection, chaining or shell builtins.
- Paths are relative to the repository root. .git, node_modules, dist, logs and .env files are blocked.
- Writes are refused unless the human enabled them. Ask before proposing a change you cannot make.
- update_task_list is shared state: other people see it. Add a task before starting work on it, and
  mark it done only when you have verified the result.
- When a tool refuses, do not retry the same call. Explain the refusal, or choose another tool.
- Finish with a short answer: what you found, what you changed (or would change), and what you verified.
"""


class SandboxError(Exception):
    """A tool call the sandbox refuses. The message goes back to the model as a tool result."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: Path = CONFIG_PATH) -> dict:
    defaults = {
        "server": {
            "endpoint": "http://127.0.0.1:9032",
            "staged_source": "node_modules/@llama-haswell",
            "runtime_dir": "runtime/llama",
            "executable": "runtime/llama/llama-server.exe",
            "model_path": "",
            "context": 8192,
            "threads": 4,
            "port": 9032,
            "server_args": ["--jinja"],
            "server_start_timeout_seconds": 180,
            "default_model": "gpt-oss-20b",
            "model": "auto",
            "timeout_seconds": 300,
            "max_tokens": 768,
            "temperature": 0.2,
            "repeat_penalty": 1.05,
        },
        "sandbox": {
            "root": "..",
            "allow_write": False,
            "allow_network": False,
            "command_timeout_seconds": 60,
            "max_output_chars": 12000,
            "max_steps": 12,
            "max_read_bytes": 200000,
            "max_write_bytes": 200000,
            "max_search_results": 80,
            "compact_tool_results": True,
            "max_tool_result_chars": 2000,
            "keep_recent_tool_results": 2,
            "keep_newest_whole": True,
            "blocked": [".git", "node_modules", "dist", "logs", ".env", ".env.local", ".env.example"],
        },
    }
    if tomllib is None or not path.is_file():
        return defaults
    with path.open("rb") as stream:
        loaded = tomllib.load(stream)
    merged = {
        "server": {**defaults["server"], **loaded.get("server", {})},
        "sandbox": {**defaults["sandbox"], **loaded.get("sandbox", {})},
        "models": dict(loaded.get("models", {})),
        "model_dir": loaded.get("model_dir", "C:/Users/canna/.models"),
    }
    return merged


class Sandbox:
    """Path confinement, program allowlisting and bounded execution. Nothing else."""

    def __init__(self, root: Path, settings: dict):
        self.root = root.resolve()
        self.settings = settings
        self.blocked = {str(part).strip().lower() for part in settings.get("blocked", []) if str(part).strip()}

    # -- paths -------------------------------------------------------------------------------------
    def resolve(self, candidate: str, *, must_exist: bool = False) -> Path:
        if not isinstance(candidate, str) or not candidate.strip():
            raise SandboxError("a path is required")
        raw = candidate.strip().replace("\\", "/")
        target = Path(raw)
        resolved = (target if target.is_absolute() else self.root / raw).resolve()
        if not resolved.is_relative_to(self.root):
            raise SandboxError(f"{candidate} resolves outside the sandbox")
        relative = resolved.relative_to(self.root)
        for part in relative.parts:
            if part.lower() in self.blocked:
                raise SandboxError(f"{candidate} touches a blocked path ({part})")
        if must_exist and not resolved.exists():
            raise SandboxError(f"{candidate} does not exist")
        return resolved

    # -- tools -------------------------------------------------------------------------------------
    def list_dir(self, path: str = ".") -> dict:
        target = self.resolve(path or ".", must_exist=True)
        if not target.is_dir():
            raise SandboxError(f"{path} is not a directory")
        entries = []
        for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if child.name.lower() in self.blocked:
                continue
            entries.append({
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "bytes": child.stat().st_size if child.is_file() else None,
            })
        return {"path": target.relative_to(self.root).as_posix() or ".", "entries": entries[:400]}

    def read_file(self, path: str, offset: int | None = None, limit: int | None = None) -> dict:
        target = self.resolve(path, must_exist=True)
        if not target.is_file():
            raise SandboxError(f"{path} is not a file")
        size = target.stat().st_size
        if size > int(self.settings.get("max_read_bytes", 200000)):
            raise SandboxError(f"{path} is larger than the read limit ({size} bytes)")
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(1, int(offset or 1))
        count = max(1, int(limit or 400))
        window = lines[start - 1 : start - 1 + count]
        return {
            "path": target.relative_to(self.root).as_posix(),
            "lines": len(lines),
            "offset": start,
            "content": "\n".join(window),
        }

    def search(self, pattern: str, path: str = ".", glob: str | None = None) -> dict:
        if not isinstance(pattern, str) or not pattern.strip():
            raise SandboxError("a pattern is required")
        try:
            regex = re.compile(pattern)
        except re.error as error:
            raise SandboxError(f"invalid regex: {error}") from error
        base = self.resolve(path or ".", must_exist=True)
        max_results = int(self.settings.get("max_search_results", 80))
        max_bytes = int(self.settings.get("max_read_bytes", 200000))
        hits = []
        candidates = [base] if base.is_file() else sorted(base.rglob(glob or "*"))
        for file in candidates:
            if len(hits) >= max_results:
                break
            if not file.is_file():
                continue
            if any(part.lower() in self.blocked for part in file.relative_to(self.root).parts):
                continue
            try:
                if file.stat().st_size > max_bytes:
                    continue
                content = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    hits.append(f"{file.relative_to(self.root).as_posix()}:{number}:{line.strip()[:240]}")
                    if len(hits) >= max_results:
                        break
        return {"pattern": pattern, "matches": hits, "truncated": len(hits) >= max_results}

    def write_file(self, path: str, content: str) -> dict:
        if not self.settings.get("allow_write"):
            raise SandboxError("writes are disabled; run the terminal with --allow-write to permit them")
        if not isinstance(content, str):
            raise SandboxError("content must be text")
        body = content.encode("utf-8")
        if len(body) > int(self.settings.get("max_write_bytes", 200000)):
            raise SandboxError(f"content exceeds the write limit ({len(body)} bytes)")
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"path": target.relative_to(self.root).as_posix(), "bytes": len(body)}

    def command_argv(self, program: str, args: list[str]) -> list[str]:
        """Validate a command and return argv. Refusal is a SandboxError, never a guess."""
        name = str(program or "").strip()
        if not name:
            raise SandboxError("a program is required")
        if name.lower() in DENIED_PROGRAMS:
            raise SandboxError(f"{name} is not available in this sandbox")
        if name not in ALLOWED_PROGRAMS:
            raise SandboxError(f"{name} is not on the program allowlist ({', '.join(sorted(ALLOWED_PROGRAMS))})")
        if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
            raise SandboxError("args must be a list of strings")
        denied = DENIED_FLAGS | (DENIED_GIT_FLAGS if name == "git" else set())
        for item in args:
            if item.split("=", 1)[0] in denied:
                raise SandboxError(f"{item.split('=', 1)[0]} is denied in this sandbox")
        allowed = ALLOWED_PROGRAMS[name]
        subcommand = next((item for item in args if item in allowed), None)
        if subcommand is None:
            raise SandboxError(f"{name} needs one of: {', '.join(sorted(allowed))}")
        return [name, *args]

    def run_command(self, program: str, args: list[str]) -> dict:
        argv = self.command_argv(program, args)
        timeout = int(self.settings.get("command_timeout_seconds", 60))
        limit = int(self.settings.get("max_output_chars", 12000))
        # A scrubbed environment: the child gets PATH and nothing else, so a token or secret in this
        # process's environment cannot leak into a command the model chose.
        env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "LANG": "C.UTF-8"}
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
                env=env,
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return {"argv": argv, "exit_code": None, "timed_out": True, "stdout": "", "stderr": f"timed out after {timeout}s"}
        except FileNotFoundError:
            return {"argv": argv, "exit_code": None, "timed_out": False, "stdout": "", "stderr": f"{program} is not installed"}
        elapsed = round(time.monotonic() - started, 3)
        return {
            "argv": argv,
            "exit_code": completed.returncode,
            "timed_out": False,
            "seconds": elapsed,
            "stdout": completed.stdout[:limit],
            "stderr": completed.stderr[:limit],
            "truncated": len(completed.stdout) > limit or len(completed.stderr) > limit,
        }

    def call(self, name: str, arguments: dict) -> dict:
        if name == "update_task_list":
            if apply_task_command is None:
                raise SandboxError("the task list is unavailable in this environment")
            action = str((arguments or {}).get("action") or "").strip().lower()
            task = str((arguments or {}).get("task") or "").strip()
            if action not in {"add", "done", "start", "block", "unblock", "remove", "list"}:
                raise SandboxError(f"unknown action: {action}")
            command = "SHOW TASKS" if action == "list" else f"{action.upper()} TASK {task}".strip()
            outcome = apply_task_command(command)
            return {"ok": outcome["ok"], "reply": outcome["reply"], "tasks": outcome["document"].get("tasks", [])}

        handlers = {
            "run_command": lambda a: self.run_command(a.get("program"), a.get("args") or []),
            "list_dir": lambda a: self.list_dir(a.get("path") or "."),
            "read_file": lambda a: self.read_file(a.get("path"), a.get("offset"), a.get("limit")),
            "search": lambda a: self.search(a.get("pattern"), a.get("path") or ".", a.get("glob")),
            "write_file": lambda a: self.write_file(a.get("path"), a.get("content", "")),
        }
        handler = handlers.get(name)
        if handler is None:
            raise SandboxError(f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            raise SandboxError("arguments must be an object")
        return handler(arguments)


# -- wire transcript compaction ----------------------------------------------------------------------
#
# The loop re-sends the whole conversation every step, so with a 2048-context model the transcript is
# what costs time: every byte of an old tool result is re-prefilled at ~5 tokens/second. The full
# output is still kept in the in-memory conversation and in the local log; what changes is only what
# goes over the wire. Older results collapse to a marker that tells the model to re-run the tool if it
# still needs them, which is cheaper than carrying a file it has already read.

def compact_text(value: str, limit: int) -> str:
    """Head and tail of a long result, with an honest marker for what was dropped.

    The marker counts against the limit: the caller asked for a bounded payload, so the result never
    exceeds it, however large the omission it reports.
    """
    text_value = value or ""
    if limit <= 0 or len(text_value) <= limit:
        return text_value
    budget = max(2, limit - 40)  # room for the marker itself
    head = max(1, (budget * 2) // 3)
    tail = max(1, budget - head)
    omitted = len(text_value) - head - tail
    marker = f"\n… [{omitted} chars omitted] …\n"
    packed = text_value[:head] + marker + text_value[-tail:]
    if len(packed) > limit:
        tail = max(0, tail - (len(packed) - limit))
        packed = text_value[:head] + marker + (text_value[-tail:] if tail else "")
    return packed


def compact_messages(
    messages: list[dict],
    *,
    result_chars: int = 2000,
    keep_recent: int = 2,
    keep_newest_whole: bool = False,
) -> list[dict]:
    """A wire copy of the conversation: recent tool results trimmed, older ones elided.

    The newest result is the one the model has to reason from, and trimming its middle is how a
    correct reading turns into a wrong one: a config file whose `[models]` table sits between the head
    and the tail looks like a file with two models. With `keep_newest_whole` the newest result is sent
    intact (still bounded by max_output_chars) and only the older results are elided, so the wire grows
    by one result per step instead of by the whole history.

    The originals are never mutated, so the terminal keeps the full record while the model gets a
    transcript that fits its context.
    """
    tool_positions = [index for index, message in enumerate(messages) if message.get("role") == "tool"]
    recent = set(tool_positions[-keep_recent:]) if keep_recent > 0 else set()
    newest = tool_positions[-1] if tool_positions else None
    wire = []
    for index, message in enumerate(messages):
        if message.get("role") != "tool":
            wire.append(message)
            continue
        content = message.get("content") or ""
        if keep_newest_whole and index == newest:
            wire.append(message)
            continue
        if index in recent:
            wire.append({**message, "content": compact_text(content, result_chars)})
        else:
            wire.append({
                **message,
                "content": f"[earlier tool result elided — {len(content)} chars; re-run the tool if you still need it]",
            })
    return wire


def wire_size(messages: list[dict]) -> int:
    return sum(len(str(message.get("content") or "")) for message in messages)


# -- llama-server REST -----------------------------------------------------------------------------

def request_json(url: str, payload: dict | None, timeout: int) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read(400).decode("utf-8", errors="replace")
        raise RuntimeError(f"llama-server HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"llama-server unavailable: {error.reason}") from error


def local_endpoint(config: dict) -> str:
    endpoint = str(config["server"]["endpoint"]).rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("the terminal only talks to a local llama-server over http://127.0.0.1")
    return endpoint


def resolve_model(config: dict, timeout: int) -> str:
    configured = str(config["server"].get("model") or "auto")
    if configured != "auto":
        return configured
    data = request_json(local_endpoint(config) + "/v1/models", None, timeout)
    models = data.get("data") or data.get("models") or []
    if not models:
        raise RuntimeError("llama-server reported no loaded model")
    name = models[0].get("id") or models[0].get("model") or models[0].get("name")
    if not isinstance(name, str) or not name:
        raise RuntimeError("llama-server returned no model name")
    return name


def parse_tool_calls(message: dict) -> list[dict]:
    """OpenAI tool_calls first; then a fenced json block, which some chat templates emit instead."""
    calls = message.get("tool_calls")
    if isinstance(calls, list) and calls:
        parsed = []
        for index, call in enumerate(calls):
            function = (call or {}).get("function") or {}
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"__unparsed__": arguments}
            parsed.append({
                "id": (call or {}).get("id") or f"call_{index}",
                "name": function.get("name") or "",
                "arguments": arguments if isinstance(arguments, dict) else {},
            })
        return [call for call in parsed if call["name"]]

    content = message.get("content") or ""
    fenced = re.search(r"```(?:json|tool_call|tool)?\s*(\{[\s\S]*?\})\s*```", content)
    if not fenced:
        return []
    try:
        candidate = json.loads(fenced.group(1))
    except json.JSONDecodeError:
        return []
    name = candidate.get("name") or candidate.get("tool")
    arguments = candidate.get("arguments") or candidate.get("parameters") or {}
    if isinstance(name, str) and name:
        return [{"id": "call_fenced", "name": name, "arguments": arguments if isinstance(arguments, dict) else {}}]
    return []


def run_task(config: dict, sandbox: Sandbox, task: str, *, max_steps: int | None = None, verbose: bool = True) -> dict:
    """One task: the model asks for tools, the sandbox answers, until the model stops or the budget ends."""
    timeout = int(config["server"]["timeout_seconds"])
    endpoint = local_endpoint(config)
    model = resolve_model(config, timeout)
    steps_budget = int(max_steps or config["sandbox"].get("max_steps", 12))

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    transcript = []
    # A model that repeats an identical call spends a whole step re-prefilling the same transcript for
    # an answer it already has. Repeats are answered from the transcript instead of re-executed.
    seen_calls = {}

    for step in range(steps_budget + 1):
        settings = config["sandbox"]
        compact = bool(settings.get("compact_tool_results", True))
        wire_messages = (
            compact_messages(
                messages,
                result_chars=int(settings.get("max_tool_result_chars", 2000)),
                keep_recent=int(settings.get("keep_recent_tool_results", 2)),
                keep_newest_whole=bool(settings.get("keep_newest_whole", True)),
            )
            if compact
            else messages
        )
        payload = {
            "model": model,
            "messages": wire_messages,
            "tools": TOOL_SCHEMAS,
            "tool_choice": "auto",
            "temperature": config["server"]["temperature"],
            "repeat_penalty": config["server"]["repeat_penalty"],
            "max_tokens": config["server"]["max_tokens"],
            "chat_template_kwargs": {"enable_thinking": False},
            "stream": False,
        }
        data = request_json(endpoint + "/v1/chat/completions", payload, timeout)
        message = ((data.get("choices") or [{}])[0].get("message")) or {}
        calls = parse_tool_calls(message)

        if not calls:
            answer = (message.get("content") or "").strip()
            transcript.append({"step": step, "kind": "answer", "content": answer, "wire_chars": wire_size(wire_messages)})
            return {"status": "ANSWERED", "answer": answer, "steps": step, "model": model, "transcript": transcript}

        messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": [
            {"id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])}}
            for call in calls
        ]})

        step_start = len(transcript)
        for call in calls:
            signature = (call["name"], json.dumps(call["arguments"], sort_keys=True, ensure_ascii=False))
            if signature in seen_calls:
                content = json.dumps({
                    "duplicate_call": True,
                    "note": f"step {seen_calls[signature]} already ran {call['name']} with these exact arguments; "
                            "its result is already in this transcript — use it, or choose different arguments",
                })
                transcript.append({"step": step, "kind": "tool", "tool": call["name"], "arguments": call["arguments"],
                                   "ok": False, "duplicate": True, "wire_chars": wire_size(wire_messages)})
                if verbose:
                    print(f"  [{call['name']}] skipped: duplicate of step {seen_calls[signature]}")
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
                continue
            seen_calls[signature] = step
            try:
                result = sandbox.call(call["name"], call["arguments"])
                content = json.dumps(result, ensure_ascii=False)
                transcript.append({"step": step, "kind": "tool", "tool": call["name"], "arguments": call["arguments"], "ok": True, "result_chars": len(content), "wire_chars": wire_size(wire_messages)})
            except SandboxError as error:
                content = json.dumps({"refused": str(error)})
                transcript.append({"step": step, "kind": "tool", "tool": call["name"], "arguments": call["arguments"], "ok": False, "refused": str(error), "wire_chars": wire_size(wire_messages)})
            if verbose:
                label = "ok" if transcript[-1]["ok"] else "refused"
                print(f"  [{call['name']}] {label}: {json.dumps(call['arguments'], ensure_ascii=False)[:160]}")
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": content[: int(config["sandbox"].get("max_output_chars", 12000))]})

        # Record what the *next* request will actually carry. Measuring the incoming request (before this
        # step's results existed) is what made an 858-char figure sit next to a 3,540-char result and look
        # like compaction had eaten it.
        outgoing = (
            compact_messages(
                messages,
                result_chars=int(settings.get("max_tool_result_chars", 2000)),
                keep_recent=int(settings.get("keep_recent_tool_results", 2)),
                keep_newest_whole=bool(settings.get("keep_newest_whole", True)),
            )
            if compact
            else messages
        )
        for entry in transcript[step_start:]:
            if entry["kind"] == "tool":
                entry["wire_chars"] = wire_size(outgoing)

    transcript.append({"step": steps_budget, "kind": "stopped", "content": "step budget exhausted"})
    return {"status": "STEP_LIMIT", "answer": "", "steps": steps_budget, "model": model, "transcript": transcript}


# -- model registry ----------------------------------------------------------------------------------
#
# One table, in patches/gpt-oss.toml, listing every local model by alias. `--model` accepts an alias, a
# bare filename or an absolute path, and the default alias is used when nothing is given, so the
# terminal never guesses which weights to load.

def model_dir(config: dict) -> Path:
    directory = str(config.get("model_dir") or "C:/Users/canna/.models")
    return Path(os.path.expandvars(os.path.expanduser(directory)))


def model_registry(config: dict) -> dict[str, str]:
    registry = config.get("models") or {}
    return {str(alias): str(target) for alias, target in registry.items() if str(alias).strip()}


def resolve_model_path(config: dict, value: str | None = None) -> Path:
    """Alias -> absolute path. A bare filename joins model_dir; an absolute path is used as given."""
    registry = model_registry(config)
    choice = str(value or "").strip() or str(config["server"].get("default_model") or "").strip()
    if not choice:
        raise ValueError("no model given; add one to [models] and set default_model in patches/gpt-oss.toml")
    target = registry.get(choice, choice)
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = model_dir(config) / target
    return candidate


def describe_models(config: dict) -> list[dict]:
    registry = model_registry(config)
    default = str(config["server"].get("default_model") or "").strip()
    rows = []
    for alias, target in sorted(registry.items()):
        path = resolve_model_path(config, alias)
        size = path.stat().st_size if path.is_file() else 0
        rows.append({
            "alias": alias,
            "path": str(path),
            "exists": path.is_file(),
            "gb": round(size / (1024 ** 3), 2) if size else None,
            "default": alias == default,
        })
    return rows


# -- local runtime staging and launch --------------------------------------------------------------

# A staged name is a leading dot, the real file name (which may itself contain dashes, as
# `llama-server.exe` does), a dash and an alphanumeric hash suffix.
STAGED_NAME = re.compile(r"^\.(?P<name>.+)-(?P<hash>[A-Za-z0-9]+)$")


def staged_binaries(source: Path) -> dict[str, Path]:
    """Map a staged file back to its real name.

    The npm package ships `.llama-server.exe-JRUIIeUq` instead of `llama-server.exe`, and it has no
    package.json to rename them, so the terminal does it. A staged name is a leading dot, the real
    file name, a dash and a hash suffix.
    """
    found = {}
    if not source.is_dir():
        return found
    for item in source.iterdir():
        if not item.is_file():
            continue
        match = STAGED_NAME.match(item.name)
        if match:
            found[match.group("name")] = item
    return found


def prepare_runtime(source: Path, target: Path, *, force: bool = False) -> dict:
    """Copy the staged binaries into runnable names. Idempotent: an unchanged size is left alone."""
    staged = staged_binaries(source)
    if not staged:
        raise ValueError(f"no staged binaries in {source}")
    target.mkdir(parents=True, exist_ok=True)
    copied, skipped = [], []
    for name, item in sorted(staged.items()):
        destination = target / name
        if destination.is_file() and not force and destination.stat().st_size == item.stat().st_size:
            skipped.append(name)
            continue
        shutil.copy2(item, destination)
        copied.append(name)
    executable = target / "llama-server.exe"
    return {
        "source": str(source),
        "target": str(target),
        "copied": copied,
        "skipped": skipped,
        "executable": str(executable) if executable.is_file() else None,
    }


def runtime_paths(config: dict) -> tuple[Path, Path]:
    base = Path(__file__).resolve().parent
    server = config["server"]
    source = Path(server.get("staged_source", "node_modules/@llama-haswell"))
    if not source.is_absolute():
        source = Path(__file__).resolve().parents[1] / source
    target = Path(server.get("runtime_dir", "runtime/llama"))
    if not target.is_absolute():
        target = base / target
    return source, target


def resolve_executable(config: dict) -> Path:
    """The runnable server: the prepared copy, or the staged source once it has been prepared."""
    server = config["server"]
    candidate = Path(server.get("executable", "runtime/llama/llama-server.exe"))
    if not candidate.is_absolute():
        candidate = Path(__file__).resolve().parent / candidate
    if candidate.is_dir():
        candidate = candidate / "llama-server.exe"
    if candidate.is_file():
        return candidate
    source, target = runtime_paths(config)
    staged = staged_binaries(source)
    if "llama-server.exe" in staged:
        prepare_runtime(source, target)
        if candidate.is_file():
            return candidate
    raise ValueError(f"llama-server.exe is missing; run: python patches/task-engine.py prepare")


def build_server_argv(config: dict, *, model_path: str | None = None) -> list[str]:
    """The llama-server command line. Loopback only, and tool calling enabled."""
    server = config["server"]
    executable = resolve_executable(config)
    resolved = resolve_model_path(config, model_path)
    model = str(resolved)
    if not resolved.is_file():
        raise ValueError(f"model file not found: {resolved}")
    argv = [
        str(executable),
        "-m", model,
        "--host", "127.0.0.1",
        "--port", str(int(server.get("port", 9032))),
        "-c", str(int(server.get("context", 8192))),
        "-t", str(int(server.get("threads", 4))),
        *[str(arg) for arg in server.get("server_args", [])],
    ]
    return argv


def start_server(config: dict, *, model_path: str | None = None) -> subprocess.Popen:
    """Start llama-server and wait for /health. The model load happens here, so the wait is generous."""
    argv = build_server_argv(config, model_path=model_path)
    endpoint = local_endpoint(config)
    timeout = int(config["server"].get("server_start_timeout_seconds", 180))
    # stdout/stderr go to a file: llama-server logs a great deal while loading, and an unread pipe
    # would fill and block the server before it ever became healthy.
    log_dir = Path(__file__).resolve().parents[1] / "logs" / "llama-server"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.log"
    log_file = log_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(argv, cwd=str(Path(argv[0]).parent), stdout=log_file, stderr=log_file, text=True)
    log_file.close()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = log_path.read_text(encoding="utf-8", errors="replace")[-600:]
            raise RuntimeError(f"llama-server exited during startup (log {log_path}): {detail.strip()}")
        try:
            with urlopen(endpoint + "/health", timeout=3) as response:
                if response.status == 200:
                    return process
        except (URLError, HTTPError, OSError):
            time.sleep(1.0)
    process.terminate()
    raise RuntimeError(f"llama-server did not become healthy within {timeout}s")


def stop_server(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


# -- CLI -------------------------------------------------------------------------------------------

def record_run(task: str, sandbox: "Sandbox", result: dict) -> Path:
    """Append one task to the transcript. Both `chat` and `launch` write here, so a launched run is
    reviewable afterwards even though the server it used has already stopped."""
    path = transcript_path()
    record = {"at": now(), "task": task, "sandbox": str(sandbox.root), **result}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    log_interaction(
        app="task-engine",
        user=task,
        assistant=result.get("answer"),
        model=result.get("model"),
        status=result.get("status"),
        tools=result.get("steps"),
    )
    return path


def transcript_path() -> Path:
    folder = Path(__file__).resolve().parents[1] / "logs" / "gpt-oss-terminal"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"


def build_sandbox(config: dict, args: argparse.Namespace) -> Sandbox:
    settings = dict(config["sandbox"])
    root = Path(args.root).expanduser() if args.root else (CONFIG_PATH.parent / settings["root"])
    if args.allow_write:
        settings["allow_write"] = True
    return Sandbox(root, settings)


def command_status(config: dict) -> int:
    endpoint = local_endpoint(config)
    source, target = runtime_paths(config)
    try:
        executable = resolve_executable(config)
        print(f"runtime:  {executable}")
    except ValueError as error:
        staged = staged_binaries(source)
        print(f"runtime:  not prepared ({error}); {len(staged)} staged file(s) in {source}")
    try:
        default_path = resolve_model_path(config)
        state = "" if default_path.is_file() else " — MISSING"
        print(f"model:    {config['server'].get('default_model') or '(none)'} → {default_path}{state}")
    except ValueError as error:
        print(f"model:    unresolved ({error})")
    try:
        health = request_json(endpoint + "/health", None, 5)
    except RuntimeError as error:
        print(f"server:   unavailable ({error})")
        return 1
    print(f"server:   {endpoint} -> {health.get('status', 'ok')}")
    try:
        print(f"loaded:   {resolve_model(config, 10)}")
    except RuntimeError as error:
        print(f"loaded:   unknown ({error})")
    return 0


def command_prepare(config: dict, args: argparse.Namespace) -> int:
    source, target = runtime_paths(config)
    if args.from_dir:
        source = Path(args.from_dir).expanduser()
    if args.to_dir:
        target = Path(args.to_dir).expanduser()
    result = prepare_runtime(source, target, force=args.force)
    print(f"staged:   {result['source']}")
    print(f"runtime:  {result['target']}")
    print(f"copied:   {', '.join(result['copied']) or '(nothing)'}")
    print(f"skipped:  {', '.join(result['skipped']) or '(nothing)'}")
    if not result["executable"]:
        print("terminal: llama-server.exe was not among the staged files", file=sys.stderr)
        return 1
    print(f"ready:    {result['executable']}")
    return 0


def command_launch(config: dict, args: argparse.Namespace) -> int:
    process = start_server(config, model_path=args.model)
    print(f"server:   started {local_endpoint(config)} (pid {process.pid})")
    try:
        if args.task:
            sandbox = build_sandbox(config, args)
            task = " ".join(args.task).strip()
            result = run_task(config, sandbox, task, max_steps=args.max_steps)
            record_run(task, sandbox, result)
            print(f"\n[{result['status']}] {result['steps']} step(s)")
            print(result["answer"] or "(no answer)")
        elif not args.keep_alive:
            print("server:   healthy; pass a task or --keep-alive to do something with it")
        if args.keep_alive:
            print("server:   running; press Ctrl+C to stop")
            while process.poll() is None:
                time.sleep(1.0)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        stop_server(process)
        print("server:   stopped")


def command_models(config: dict, args: argparse.Namespace) -> int:
    rows = describe_models(config)
    if not rows:
        print("no models registered; add them under [models] in patches/gpt-oss.toml", file=sys.stderr)
        return 1
    width = max(len(row["alias"]) for row in rows)
    print(f"model dir: {model_dir(config)}")
    missing = 0
    for row in rows:
        state = "ok" if row["exists"] else "MISSING"
        if not row["exists"]:
            missing += 1
        marker = "*" if row["default"] else " "
        size = f"{row['gb']:>6.2f} GB" if row["gb"] else "     ? GB"
        print(f"{marker} {row['alias'].ljust(width)}  {size}  {state:8}  {row['path']}")
    print("\n* default; launch with: python patches/task-engine.py launch --model <alias>")
    return 0 if missing == 0 else 1


def command_tasks(config: dict, args: argparse.Namespace) -> int:
    if render_tasks is None:
        print("the task list is unavailable in this environment", file=sys.stderr)
        return 1
    if args.command_text:
        outcome = apply_task_command(" ".join(args.command_text))
        print(outcome["reply"])
        return 0 if outcome["ok"] else 1
    from task_list import load
    print(render_tasks(load()))
    return 0


def command_tools(config: dict, args: argparse.Namespace) -> int:
    sandbox = build_sandbox(config, args)
    print(f"sandbox root: {sandbox.root}")
    print(f"writes:       {'enabled' if sandbox.settings.get('allow_write') else 'refused'}")
    for schema in TOOL_SCHEMAS:
        function = schema["function"]
        params = ", ".join((function.get("parameters", {}).get("properties") or {}).keys())
        print(f"  {function['name']}({params})")
    print(f"programs:     {', '.join(sorted(ALLOWED_PROGRAMS))}")
    return 0


def command_chat(config: dict, args: argparse.Namespace) -> int:
    sandbox = build_sandbox(config, args)
    task = " ".join(args.task).strip() if args.task else ""
    if not task:
        print("terminal: a task is required", file=sys.stderr)
        return 2
    result = run_task(config, sandbox, task, max_steps=args.max_steps)
    record_run(task, sandbox, result)
    print(f"\n[{result['status']}] {result['steps']} step(s)")
    print(result["answer"] or "(no answer)")
    return 0 if result["status"] == "ANSWERED" else 1


def command_shell(config: dict, args: argparse.Namespace) -> int:
    sandbox = build_sandbox(config, args)
    print(f"gpt-oss terminal · sandbox {sandbox.root} · writes {'on' if sandbox.settings.get('allow_write') else 'off'}")
    print("Type a task. 'exit' leaves. Each task starts from a clean conversation.")
    while True:
        try:
            task = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if task.lower() in {"exit", "quit"}:
            return 0
        if not task:
            continue
        result = run_task(config, sandbox, task, max_steps=args.max_steps)
        print(result["answer"] or f"({result['status']})")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = load_config()
    parser = argparse.ArgumentParser(description="Sandboxed terminal for gpt-oss over llama-server.")
    parser.add_argument("--root", help="Sandbox root (defaults to the repository)")
    parser.add_argument("--allow-write", action="store_true", help="Permit write_file inside the sandbox")
    parser.add_argument("--max-steps", type=int, help="Tool round trips per task")
    parser.add_argument("--max-tokens", type=int, help="Cap on generated tokens per model turn")
    parser.add_argument("--executable", help="llama-server executable or its directory (overrides the config)")
    parser.add_argument("--context", type=int, help="Context window for the launched server (KV cache costs memory)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Report the runtime, the model and the server")
    sub.add_parser("tools", help="List the sandbox tools and allowlisted programs")
    sub.add_parser("models", help="List every registered model, its size and whether the file is present")
    tasks = sub.add_parser("tasks", help="Show the shared task list, or run one AIML command against it")
    tasks.add_argument("command_text", nargs=argparse.REMAINDER)
    prepare = sub.add_parser("prepare", help="Copy the staged llama-haswell binaries into runnable names")
    prepare.add_argument("--from-dir", help="Staged source directory (default: node_modules/@llama-haswell)")
    prepare.add_argument("--to-dir", help="Runtime directory (default: patches/runtime/llama)")
    prepare.add_argument("--force", action="store_true", help="Copy even when the size already matches")
    launch = sub.add_parser("launch", help="Start llama-server, optionally run one task, then stop it")
    launch.add_argument("--model", help="Model alias from [models], a filename, or an absolute path (default: default_model)")
    launch.add_argument("--task", nargs=argparse.REMAINDER, help="Task to run once the server is healthy")
    launch.add_argument("--keep-alive", action="store_true", help="Leave the server running until Ctrl+C")
    chat = sub.add_parser("chat", help="Run one task against an already-running server")
    chat.add_argument("task", nargs=argparse.REMAINDER)
    sub.add_parser("shell", help="Interactive terminal")

    args = parser.parse_args(argv)
    if getattr(args, "max_tokens", None):
        config["server"]["max_tokens"] = int(args.max_tokens)
    if getattr(args, "executable", None):
        config["server"]["executable"] = args.executable
    if getattr(args, "context", None):
        config["server"]["context"] = int(args.context)
    try:
        if args.command == "status":
            return command_status(config)
        if args.command == "tools":
            return command_tools(config, args)
        if args.command == "models":
            return command_models(config, args)
        if args.command == "tasks":
            return command_tasks(config, args)
        if args.command == "prepare":
            return command_prepare(config, args)
        if args.command == "launch":
            return command_launch(config, args)
        if args.command == "chat":
            return command_chat(config, args)
        return command_shell(config, args)
    except (ValueError, RuntimeError) as error:
        print(f"terminal: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
