# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "textual>=0.58.0",
#     "openai>=1.40.0",
#     "pydantic>=2.0",
#     "python-aiml",
#     "requests",
#     "beautifulsoup4",
#     "Pillow>=10.0",
#     "textual-image",
# ]
# ///
import os
import re
try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None
try:  # shared interaction log; the dumper compiles these pairs into AIML
    from interaction_log import log_interaction
except ImportError:  # pragma: no cover
    def log_interaction(**kwargs):
        return None
try:  # the task-list bus renders in the right-hand panel and accepts AIML commands
    from task_list import TaskListBus, render_panel
except ImportError:  # pragma: no cover
    TaskListBus = None
    def render_panel(document):
        return ["(task list unavailable)"]
try:  # the one place that edits gpt-oss.toml, shared with the terminal and start.bat
    from model_config import set_default_model as persist_default_model
except ImportError:  # pragma: no cover
    persist_default_model = None
try:  # session transcripts, so a conversation can be resumed or rewound
    import session_log
except ImportError:  # pragma: no cover
    session_log = None
# Prefer a dedicated terminal-image widget; keep the Rich half-block renderer as fallback.
try:
    from textual_image.widget import Image as TerminalImage
except ImportError:
    TerminalImage = None
try:
    import png_logo
except ImportError:
    png_logo = None
try:  # typed contracts for the tools, and the plan composer that admits compositions
    import functions
    import planner
except ImportError:  # pragma: no cover
    functions = None
    planner = None
try:  # the K'UHUL phase package, read as data (digests verified before a bank is learned)
    import phases
except ImportError:  # pragma: no cover
    phases = None
try:  # the six-phase daemon bot engine: one cycle per turn, plus the mode bias vectors
    import daemon
except ImportError:  # pragma: no cover
    daemon = None
try:  # append-only user memory: JSONL history, GML projection, writes behind a grant
    import user_memory
except ImportError:  # pragma: no cover
    user_memory = None
try:  # commit / push / build / clone, on command and behind a grant
    import gitops
except ImportError:  # pragma: no cover
    gitops = None
try:  # the reachable loopback endpoint: micronaut://v1/chat
    import micronaut_server
except ImportError:  # pragma: no cover
    micronaut_server = None
try:  # Greeting-µ: the greeting graph, used to keep every intent in a multi-intent utterance
    import greetings
except ImportError:  # pragma: no cover
    greetings = None
try:  # the curated ALICE knowledge banks the kernel learns first
    import knowledge
except ImportError:  # pragma: no cover
    knowledge = None
try:  # clickable reference links for a topic
    import links
except ImportError:  # pragma: no cover
    links = None
try:  # retrieval and composition: the two contracts that were declared but never consumed
    import compose
except ImportError:  # pragma: no cover
    compose = None
try:  # the phase chain as the first routing boundary
    import phase_routing
except ImportError:  # pragma: no cover
    phase_routing = None
try:  # live evidence capture for every turn
    import evidence_record
except ImportError:  # pragma: no cover
    evidence_record = None
try:  # the read-only runtime projection behind /runtime
    import runtime_tree
except ImportError:  # pragma: no cover
    runtime_tree = None
try:  # one long-lived lifecycle: leases for the streamed path, and the idle sweep
    import model_lifecycle
    import inference_session
except ImportError:  # pragma: no cover
    model_lifecycle = None
    inference_session = None
try:  # cheap staleness hint: the poll skips a rebuild when nothing bumped
    import runtime_signals
except ImportError:  # pragma: no cover
    runtime_signals = None
try:  # observed phase events: what the host did, never what a model claimed
    import phase_events
except ImportError:  # pragma: no cover
    phase_events = None
try:  # local profile: configuration the bot may read, never a grant
    import profile as user_profile
except ImportError:  # pragma: no cover
    user_profile = None
import math
import tempfile
import shlex
import subprocess
import threading
import time
import uuid
import shutil
import requests
import webbrowser
from datetime import datetime
from pathlib import Path
from enum import Enum
from typing import Callable
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits
from textual.command import Provider as CommandProvider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.fuzzy import Matcher
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Header, Input, Footer, Markdown, Static
from rich.text import Text as RichText
from openai import OpenAI, pydantic_function_tool
from pydantic import BaseModel, Field
import aiml
try:
    from mu import Micronaut
except ImportError:
    Micronaut = None
from bs4 import BeautifulSoup
from functools import partial
from urllib.parse import quote_plus

# gpt-oss.toml lives here, so this is the repository root: the sandbox, the corpus, .env, the task
# list and the logs all resolve against it, never against the shell's working directory.
APP_ROOT = Path(__file__).resolve().parent


def load_env(path: Path = APP_ROOT / ".env") -> dict[str, str]:
    """Read KEY=value pairs from .env into os.environ; a real environment variable always wins.

    Only the optional cloud advisors need a secret, and start.bat is what writes it here. The file
    is gitignored and on the sandbox blocklist, so it can never be read by the model.
    """
    loaded: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")  # tolerate a BOM from any editor
    except OSError:
        return loaded
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value:
            loaded[key] = value
            os.environ.setdefault(key, value)
    return loaded


ADVISOR_KEYS = load_env()

# =====================================================================
# 1. THE SANDBOX (Adapted from task-engine.py)
# =====================================================================
ALLOWED_PROGRAMS = {
    "git": {"status", "diff", "log", "show", "ls-files", "rev-parse", "branch", "grep", "describe"},
    "python": {"-c", "-m", "-V", "--version"},
    "node": {"-e", "-v", "--version", "-p", "--print"},
}
DENIED_FLAGS = {"--output", "-o", "--exec-path", "--upload-pack", "--receive-pack", "--git-dir", "--work-tree", "--config"}
DENIED_PROGRAMS = {"rm", "del", "format", "curl", "wget", "ssh", "powershell", "cmd", "sh", "bash", "sudo"}
BLOCKED_PATHS = {".git", "node_modules", "dist", "logs", ".env", ".env.local"}

class SandboxError(Exception):
    pass

class Sandbox:
    """Reads are always allowed inside the workspace; writes and patches need the human's grant.

    The grant is per workspace and is dropped the moment a different folder is picked, so granting
    writes in one project cannot quietly follow you into another.
    """

    MAX_WRITE = 200_000

    def __init__(self, root: Path, *, allow_write: bool = False):
        self.root = Path(root).resolve()
        self.allow_write = allow_write

    def set_root(self, root: Path, *, allow_write: bool = False) -> Path:
        self.root = Path(root).resolve()
        self.allow_write = allow_write
        return self.root

    @property
    def mode(self) -> str:
        return "read-write" if self.allow_write else "read-only"

    def resolve(self, path_str: str, must_exist=False) -> Path:
        if not path_str: raise SandboxError("path required")
        raw = path_str.strip().replace("\\", "/")
        target = (self.root / raw).resolve()
        if not target.is_relative_to(self.root):
            raise SandboxError(f"Path '{path_str}' escapes sandbox root")
        for part in target.relative_to(self.root).parts:
            if part.lower() in BLOCKED_PATHS:
                raise SandboxError(f"Path '{path_str}' touches blocked dir: {part}")
        if must_exist and not target.exists():
            raise SandboxError(f"Path '{path_str}' does not exist")
        return target

    def list_dir(self, path="."):
        target = self.resolve(path, must_exist=True)
        if not target.is_dir(): raise SandboxError("not a directory")
        entries = []
        for child in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if child.name.lower() in BLOCKED_PATHS: continue
            entries.append(f"{'[DIR]' if child.is_dir() else '[FILE]'} {child.name}")
        return "\n".join(entries[:200]) or "(empty)"

    def read_file(self, path):
        target = self.resolve(path, must_exist=True)
        if not target.is_file(): raise SandboxError("not a file")
        if target.stat().st_size > 200_000: raise SandboxError("file too large")
        return target.read_text(encoding="utf-8", errors="replace")[:4000] # Return first 4000 chars

    def write_file(self, path: str, content: str) -> str:
        """Create or replace a text file inside the workspace. Needs the write grant."""
        if not self.allow_write:
            raise SandboxError("workspace is read-only; `/allow` grants writes and patches")
        body = "" if content is None else str(content)
        if len(body.encode("utf-8")) > self.MAX_WRITE:
            raise SandboxError(f"refusing to write more than {self.MAX_WRITE} bytes")
        target = self.resolve(path)
        if target.is_dir():
            raise SandboxError("that path is a directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8", newline="\n")
        return f"wrote {len(body)} char(s) to {target.relative_to(self.root).as_posix()}"

    def patch_file(self, path: str, find: str, replace: str, replace_all: bool = False) -> str:
        """Replace `find` with `replace` in a file. Ambiguous or absent matches are refused."""
        if not self.allow_write:
            raise SandboxError("workspace is read-only; `/allow` grants writes and patches")
        if not find:
            raise SandboxError("patch needs something to find")
        target = self.resolve(path, must_exist=True)
        if not target.is_file():
            raise SandboxError("not a file")
        if target.stat().st_size > self.MAX_WRITE:
            raise SandboxError("file too large to patch")
        text = target.read_text(encoding="utf-8", errors="replace")
        hits = text.count(find)
        if not hits:
            raise SandboxError("that text is not in the file")
        if hits > 1 and not replace_all:
            raise SandboxError(f"'{find[:40]}' appears {hits} times; narrow it or pass replace_all")
        updated = text.replace(find, "" if replace is None else str(replace), -1 if replace_all else 1)
        target.write_text(updated, encoding="utf-8", newline="\n")
        return f"patched {target.relative_to(self.root).as_posix()} ({1 if not replace_all else hits} replacement(s))"

    def run_command(self, program: str, args: list[str]):
        if program not in ALLOWED_PROGRAMS:
            raise SandboxError(f"{program} is not allowlisted")
        if any(a.split("=")[0] in DENIED_FLAGS for a in args):
            raise SandboxError("denied flag passed")
        # The allowlist is per subcommand, the same way the terminal enforces it: `git push` and
        # `python -c` both go through here, and only the second is on the list.
        allowed = ALLOWED_PROGRAMS[program]
        if allowed and not any(item in allowed for item in args):
            raise SandboxError(f"{program} needs one of: {', '.join(sorted(allowed))}")

        argv = [program] + args
        try:
            # Decode explicitly: the platform default is cp1252 here, and any byte outside it (an
            # em-dash in a diff, a box-drawing character in output) makes capture fail with
            # stdout=None - which then looked like "'NoneType' object has no attribute 'strip'".
            res = subprocess.run(argv, cwd=str(self.root), capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=10, shell=False)
            out = ((res.stdout or "").strip() or (res.stderr or "").strip()
                   or f"(no output · exit {res.returncode})")
            return out[:2000]
        except Exception as e:
            return str(e)

# The default workspace is the repository root (APP_ROOT above), so the model cannot wander into the
# profile until a human points it somewhere else with /workspace.
sandbox = Sandbox(APP_ROOT)

# =====================================================================
# 2. TOOLS & INTENTS
# =====================================================================
class ListDirArgs(BaseModel):
    path: str = Field(".", description="Relative path to list")
class ReadFileArgs(BaseModel):
    path: str = Field(..., description="Relative path to read")
class RunCommandArgs(BaseModel):
    program: str = Field(..., description="Allowlisted program: git, python, node (python/node take -c/-m/-e)")
    args: list[str] = Field(..., description="Arguments, e.g. ['status'] for git status")
class GitArgs(BaseModel):
    command: str = Field(..., description="Read-only git subcommand: status, diff, log, show, branch, ls-files, grep, describe")
    arguments: list[str] = Field(default_factory=list, description="Extra arguments, e.g. ['--oneline', '-10'] for log")
class HistoryArgs(BaseModel):
    query: str = Field("", description="Text to look for in earlier sessions; empty lists the newest messages")
    limit: int = Field(10, description="How many messages to return at most")
class WriteFileArgs(BaseModel):
    path: str = Field(..., description="Workspace-relative path to write")
    content: str = Field(..., description="Full file content; only when the workspace is read-write")
class PatchFileArgs(BaseModel):
    path: str = Field(..., description="Workspace-relative file to patch")
    find: str = Field(..., description="Exact text to replace, long enough to appear once")
    replace: str = Field("", description="Replacement text; empty string deletes the match")
    replace_all: bool = Field(False, description="Replace every occurrence instead of refusing ambiguity")
class CloneArgs(BaseModel):
    url: str = Field(..., description="https repository url to clone into the workspace")
    path: str = Field("", description="Workspace-relative destination directory; empty derives it from the url")
    depth: int = Field(1, description="Shallow clone depth (1 = only the tip)")


class GmlValidateArgs(BaseModel):
    path: str = Field(..., description="Workspace-relative .gml document to validate against the tensor registry")
class GmlAssembleArgs(BaseModel):
    graph_id: str = Field("tensor/assembled", description="Which assembly document to plan, e.g. tensor/assembled")


def format_history(rows: list[dict]) -> str:
    """The model's view of the transcript: when, which session, who, and a bounded excerpt."""
    if not rows:
        return "no earlier messages recorded yet"
    lines = []
    for row in rows:
        when = str(row.get("at") or "")[:16].replace("T", " ")
        lines.append(f"[{when}] {str(row.get('session') or '')[:6]} {row.get('role')}: {str(row.get('content') or '')[:400]}")
    return "\n".join(lines)


def run_registered_gml(name: str, args: dict) -> str:
    """Run one registered GML function for the model, through the typed registry."""
    if functions is None:
        return "the function registry is unavailable"
    entry = functions.get(name)
    if entry is None or entry.handler is None:
        return f"{name} is not registered in this build"
    context = functions.ToolContext(Path(sandbox.root), sandbox)
    try:
        if name == "gml_validate":
            rows = entry.handler(context, [{"path": str(args.get("path") or "")}])
            return "\n".join(f"{row['state']}: {row['file']} — {row['detail']}" for row in rows) or "nothing to validate"
        if name == "gml_assemble":
            return str(entry.handler(context, str(args.get("graph_id") or "")))
        return str(entry.handler(context))
    except Exception as error:
        return f"{name} failed: {error}"


def execute_tool(name: str, args: dict) -> str:
    try:
        if name == "list_dir":
            return sandbox.list_dir(args.get("path", "."))
        elif name == "read_file":
            return sandbox.read_file(args["path"])
        elif name == "clone_repo":
            # Creating a directory tree from the network is a write: the grant is checked here as well
            # as in the tool list, because a model can name a tool it was not offered.
            if gitops is None:
                return "the git operations module is unavailable"
            if not sandbox.allow_write:
                return ("clone refused: the workspace is read-only "
                        "(`/allow` grants writes, and this creates files)")
            outcome = gitops.clone(str(args.get("url") or ""), args.get("path") or None,
                                   root=sandbox.root, depth=args.get("depth") or 1)
            if not outcome["ok"]:
                return f"clone failed ({outcome.get('exit_code')}):\n{outcome['output']}"
            return (f"cloned into {outcome['path']} ({outcome.get('branch')} @ {outcome.get('head')})\n"
                    f"{outcome['output']}")
        elif name == "run_command":
            return sandbox.run_command(args["program"], args["args"])
        elif name == "git_command":
            extra = [str(item) for item in (args.get("arguments") or [])]
            return sandbox.run_command("git", [str(args.get("command") or "status")] + extra)
        elif name == "search_history":
            if session_log is None:
                return "session logging is unavailable"
            rows = session_log.search(str(args.get("query") or ""), limit=int(args.get("limit") or 10))
            return format_history(rows)
        elif name == "write_file":
            return sandbox.write_file(args["path"], args.get("content", ""))
        elif name == "patch_file":
            return sandbox.patch_file(args["path"], args["find"], args.get("replace", ""), bool(args.get("replace_all")))
        elif name in {"gml_validate", "gml_assemble", "gml_registry"}:
            # Whatever the K'UHUL base currently declares, through the same registry the plans use.
            return run_registered_gml(name, args)
    except SandboxError as e:
        return f"🚫 [Sandbox Refused]: {e}"
    except Exception as e:
        return f"❌ [Error]: {e}"
    return "Unknown tool"

# Regex Fast-Path (for Instant local execution)
def check_regex_fast_path(text: str):
    text_lower = text.lower()
    # Web search: this build has no web tool, so a match is a request we must answer honestly rather
    # than fabricate a result for.
    search_match = re.search(r"(?:search(?: the)? web for|look up) (.*)", text_lower)
    if search_match: return "search_web", search_match.group(1).strip()
    # Math: computed locally, and only when it really parses.
    math_match = re.search(r"(?:calculate|math) (.*)", text_lower)
    if math_match: return "compute_math", math_match.group(1).strip()
    return None, None


def safe_math(expression: str) -> str | None:
    """Evaluate arithmetic without eval: numbers, + - * / // % ** and parentheses only."""
    import ast
    import operator

    operators = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                 ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
                 ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
                 ast.UAdd: operator.pos}

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 512:
                raise ValueError("exponent too large")
            return operators[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in operators:
            return operators[type(node.op)](walk(node.operand))
        raise ValueError(f"not arithmetic: {type(node).__name__}")

    if not expression or len(expression) > 200:
        return None
    try:
        value = walk(ast.parse(expression, mode="eval"))
    except Exception:
        return None
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def fast_path_outcome(text: str) -> dict | None:
    """What the fast path should do with this text, decided without touching the model.

    Returns None when there is nothing to do. A web request is *not* a result: no web tool is wired
    into this build, so the honest action is to say so and let the model answer from training data.
    """
    intent, argument = check_regex_fast_path(text)
    if intent == "search_web":
        return dict(action="explain_no_web", argument=argument,
                    note=(f"No web tool in this build, so I cannot search for \"{argument}\". "
                          "The model can answer from its training data (which may be out of date) - "
                          "it cannot browse either."))
    if intent == "compute_math":
        result = safe_math(argument)
        if result is None:
            return dict(action="defer", argument=argument,
                        note=f"\"{argument}\" is not arithmetic I can evaluate locally.")
        return dict(action="math", argument=argument, result=result,
                    note=f"{argument} = {result}")
    return None

# =====================================================================
# 3. THE AGENT (LLM + Tools)
# =====================================================================
def load_terminal_config() -> dict:
    """Read the same gpt-oss.toml the terminal uses.

    One table of models means the chat app and the terminal can never disagree about which weights an
    alias points at, or which one is the default.
    """
    config_path = Path(__file__).resolve().parent / "gpt-oss.toml"
    if tomllib is None or not config_path.is_file():
        return {}
    try:
        with config_path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, ValueError):
        return {}


TERMINAL_CONFIG = load_terminal_config()
MODEL_DIR = Path(os.path.expanduser(str(TERMINAL_CONFIG.get("model_dir") or "C:/Users/canna/.models")))
MODEL_REGISTRY = {str(alias): str(target) for alias, target in (TERMINAL_CONFIG.get("models") or {}).items()}
DEFAULT_MODEL_ALIAS = str((TERMINAL_CONFIG.get("server") or {}).get("default_model") or "gpt-oss-20b")
LLAMA_ENDPOINT = str((TERMINAL_CONFIG.get("server") or {}).get("endpoint") or "http://127.0.0.1:9032").rstrip("/")


def model_path_for(alias: str) -> Path:
    target = MODEL_REGISTRY.get(alias, alias)
    path = Path(target)
    return path if path.is_absolute() else MODEL_DIR / target


def ordered_models() -> list[str]:
    """Aliases in gpt-oss.toml order: fastest first, deepest last. The table is the speed dial."""
    return list(MODEL_REGISTRY)


def tier_for(alias: str) -> str:
    """Speed tier read off the weights themselves, so the label cannot drift from the file."""
    path = model_path_for(alias)
    if not path.is_file():
        return "unavailable"
    gb = path.stat().st_size / (1024 ** 3)
    if gb < 1:
        return "fastest"
    if gb < 1.5:
        return "fast"
    if gb < 3:
        return "balanced"
    if gb < 8:
        return "strong"
    return "deep"


class Provider(Enum):
    OLLAMA = "ollama"
    LLAMA_SERVER = "llama-server"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    ANTHROPIC = "anthropic"

# Where a human goes to get the credential (or the local daemon) for each provider. Printed with
# markdown links, so a terminal that speaks OSC 8 makes the address clickable; the palette entries
# open the browser outright for terminals that do not.
KEY_PAGES = {
    Provider.OPENAI: ("platform.openai.com/api-keys", "https://platform.openai.com/api-keys"),
    Provider.DEEPSEEK: ("platform.deepseek.com/api_keys", "https://platform.deepseek.com/api_keys"),
    Provider.ANTHROPIC: ("platform.claude.com/settings/keys", "https://platform.claude.com/settings/keys"),
    Provider.OLLAMA: ("ollama.com/download", "https://ollama.com/download"),
}

# Cloud advisors read their token from the environment, which load_env() filled from .env. A missing
# key is a normal state, not an error: the app stays on the local server until one exists.
CLOUD_PROVIDERS = {Provider.OPENAI, Provider.DEEPSEEK, Provider.ANTHROPIC}
ADVISOR_ENV = {
    Provider.OPENAI: "OPENAI_API_KEY",
    Provider.DEEPSEEK: "DEEPSEEK_API_KEY",
    Provider.ANTHROPIC: "ANTHROPIC_API_KEY",
}

PROVIDER_CONFIGS = {
    Provider.OLLAMA: {"base_url": "http://localhost:11434/v1", "api_key": "ollama", "default_model": "llama3"},
    # The local llama-server the terminal launches; it serves one model, so "auto" is resolved from
    # /v1/models rather than assumed.
    Provider.LLAMA_SERVER: {"base_url": LLAMA_ENDPOINT + "/v1", "api_key": "local", "default_model": "auto"},
    Provider.OPENAI: {"base_url": None, "api_key": os.environ.get("OPENAI_API_KEY"), "default_model": "gpt-4o"},
    Provider.DEEPSEEK: {"base_url": "https://api.deepseek.com/v1", "api_key": os.environ.get("DEEPSEEK_API_KEY"), "default_model": "deepseek-chat"},
    # Claude speaks the OpenAI wire format through its compatibility layer; the model id is the one
    # Anthropic documents as the best speed/intelligence trade-off. Change it here for another Claude.
    Provider.ANTHROPIC: {"base_url": "https://api.anthropic.com/v1", "api_key": os.environ.get("ANTHROPIC_API_KEY"), "default_model": "claude-sonnet-5-5"},
}

class Prompt(Markdown): BORDER_TITLE = "You"
class Response(Markdown): BORDER_TITLE = "Assistant"
class ToolLog(Markdown): BORDER_TITLE = "System Log"

class ChatCommands(CommandProvider):
    """Ctrl+P palette. One entry per model, in gpt-oss.toml order — fastest first, deepest last."""

    async def discover(self) -> Hits:
        for label, callback, help_text in self.app.get_commands().values():
            yield DiscoveryHit(label, callback, text=label, help=help_text)

    async def search(self, query: str) -> Hits:
        matcher = Matcher(query)
        for label, callback, help_text in self.app.get_commands().values():
            score = matcher.match(label)
            if score > 0:
                yield Hit(score, matcher.highlight(label), callback, text=label, help=help_text)

class LogoArt(Static):
    """Display logo.png as nearest-neighbor terminal half-block pixels."""

    DEFAULT_CSS = """
    LogoArt { width: 22; height: 11; content-align: center middle; }
    """

    def __init__(self, *, cols: int = 20, rows: int = 20, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self.cols = cols
        self.rows = rows
        self.logo = None
        self.problem = ""

    def on_mount(self) -> None:
        if png_logo is None:
            self.problem = "logo: install textual-image, or provide png_logo.py and Pillow"
        else:
            try:
                self.logo = png_logo.load_default()
            except Exception as error:
                self.problem = f"logo: {error}"
        self.draw()

    def draw(self) -> None:
        if self.problem:
            self.update(self.problem)
            return
        try:
            self.update(self.logo.render(self.cols, self.rows))
        except Exception as error:
            self.problem = f"logo: {error}"
            self.update(self.problem)


def terminal_logo_path(source: Path) -> Path:
    """Letterbox the PNG for 16x12 terminal cells (roughly 16x24 pixels).

    The image widget may stretch its input to its CSS rectangle. Preparing
    a correctly proportioned canvas prevents the logo itself being squashed.
    """
    from PIL import Image as PILImage, ImageOps

    with PILImage.open(source) as original:
        if original.width * original.height > 1_048_576:
            raise ValueError("logo exceeds 1 megapixel")
        # Use a 2:3 pixel canvas: 16 columns x 12 double-height cells.
        canvas = PILImage.new("RGBA", (320, 480), (0, 0, 0, 0))
        fitted = ImageOps.contain(original.convert("RGBA"), canvas.size, PILImage.Resampling.LANCZOS)
        canvas.alpha_composite(fitted, ((320 - fitted.width) // 2, (480 - fitted.height) // 2))
        target = Path(tempfile.gettempdir()) / "knumatic-logo-terminal-16x12.png"
        canvas.save(target, format="PNG")
        return target


class WorkspaceBar(Static):
    """Which folder the model may touch, in which mode, and which session is recording it."""

    def show(self, root: Path, mode: str, session: str) -> None:
        home = Path.home()
        try:
            shown = "~/" + Path(root).relative_to(home).as_posix()
        except ValueError:
            shown = str(root)
        text = RichText()
        text.append("workspace  ", style="bold")
        text.append(shown)
        text.append("   ·   ", style="dim")
        text.append(mode, style="green" if mode == "read-write" else "yellow")
        text.append("   ·   ", style="dim")
        text.append("/workspace  /allow", style="dim")
        self.update(text)


class WorkspacePicker(ModalScreen[Path | None]):
    """Folder chooser. Enter expands, `a` takes the highlighted folder, Escape cancels."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("a", "use_current", "Use this folder"),
    ]

    DEFAULT_CSS = """
    WorkspacePicker { align: center middle; }
    WorkspacePicker > Vertical { width: 90; height: 80%; border: round $accent; background: $surface; padding: 1; }
    WorkspacePicker #picker-title { height: auto; padding: 0 0 1 0; }
    WorkspacePicker DirectoryTree { height: 1fr; }
    """

    def __init__(self, start: Path) -> None:
        super().__init__()
        self.start = Path(start)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                f"Workspace folder — Enter expands, `a` picks the highlighted one, Escape cancels\n{self.start}",
                id="picker-title",
                markup=False,
            )
            yield DirectoryTree(str(self.start), id="picker-tree")

    @on(DirectoryTree.DirectorySelected)
    def picked_directory(self, event: DirectoryTree.DirectorySelected) -> None:
        self.dismiss(Path(str(event.path)))

    def action_use_current(self) -> None:
        node = self.query_one(DirectoryTree).cursor_node
        data = getattr(node, "data", None)
        self.dismiss(Path(str(data.path)) if data is not None else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


AFFIRMATIVE = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|ok|okay|please|go on|go ahead|do it|tell me more|delve deeper|"
    r"more|continue|absolutely|yes please|please do)\b", re.I)


# A generation counter cannot see another process's edits, so re-read the registries every N ticks.
RECONCILE_EVERY = 15

COMMANDS = App.COMMANDS | {ChatCommands}


class ChatApp(App):
    # The palette is the model switcher: system commands (screen, quit…) plus ChatCommands below.
    CSS = """
    Screen { layout: vertical; width: 100%; height: 100%; overflow: hidden; }
    /* The mark is a title, not a poster: 128x85 source, 22x11 box (10 art rows). */
    #welcome-logo-row { width: 100%; height: 11; min-height: 11; max-height: 11; align: center middle; }
    #welcome-logo { width: 22; height: 11; min-height: 11; max-height: 11; }
    #main { height: 1fr; min-height: 0; width: 100%; }
    #chat-view { width: 2fr; height: 1fr; min-height: 0; padding: 1 2; background: $surface; }
    #task-panel { width: 1fr; height: 1fr; min-height: 0; border: round $secondary; padding: 0 1; }
    #task-title { content-align: center middle; text-style: bold; height: 1; }
    #task-section { height: 1fr; min-height: 5; }
    #task-body { height: 1fr; overflow-y: auto; }
    #history-section { height: 1fr; min-height: 7; border-top: solid $secondary; padding-top: 1; }
    #history-title { height: 1; content-align: center middle; text-style: bold; }
    #history-body { height: 1fr; overflow-y: auto; color: $text-muted; }
    #history-help { height: 2; color: $text-muted; }
    Prompt { border: round $primary; margin: 1 0; padding: 1; background: $primary 10%; }
    Response { border: round $success; margin: 1 0; padding: 1; background: $success 10%; }
    ToolLog { border: round $warning; margin: 1 0; padding: 1; background: $warning 10%; color: $text-muted; }
    Input { margin: 0 1; height: 3; }
    #completion-hint { height: 1; padding: 0 2; color: $text-muted; }
    #workspace-bar { height: 2; width: 1fr; padding: 0 2; content-align: left middle; background: $surface; color: $text-muted; }
    """
    AUTO_FOCUS = "Input"
    BINDINGS = [Binding("ctrl+space", "accept_completion", "Complete", priority=True)]

    def __init__(self):
        super().__init__()
        # Local first: runtime/llama serves the weights, so the app is useful with no keys and no
        # network. Cloud providers are advisors — reached from the palette or /advisor <name> —
        # never the default.
        self.current_provider = Provider.LLAMA_SERVER
        self.client = None
        self.model_name = ""
        # Every conversation is a session on disk: /resume and /rewind work off that file, and the
        # model can look back at it with the search_history tool.
        self.session_id = session_log.new_session() if session_log else ""
        self.messages = [{"role": "system", "content": self.system_prompt()}]
        self.bus = TaskListBus().start() if TaskListBus else None
        self.update_client()
        self.router = self.get_semantic_router()
        self.completion = Micronaut({"sandbox": self.completion_registry()}) if Micronaut else None
        self.current_completion = ""
        # Every turn goes through the six-phase cycle; the engine records what each phase decided
        # and its closure is what `/daemon` shows. It proposes, the gates below admit.
        self.mode = ""
        self.last_turn = None
        # Memory is scoped to one identity, and writes are a grant like /allow.
        self.user_id = user_memory.DEFAULT_USER if user_memory else "local-user"
        self.memory_write = False
        # Repo writes (add/commit/push) are a separate grant from file writes: /allow git.
        self.git_write = False
        # The loopback endpoint, when the human starts one (/serve).
        self.server = None
        # The phase chain's verdict for the last turn, kept so /daemon and /plan can show it.
        self.last_plan = None
        self.last_routing = None
        # The green screen: a digest of the last render, and counters a guard can read.
        self.last_tree = None
        self.runtime_digest = None
        self.runtime_polls = 0
        self.runtime_renders = 0
        # One lifecycle for the whole app: leases, ownership and the idle sweep all live here.
        self.lifecycle = (model_lifecycle.Lifecycle(model_lifecycle.load())
                          if model_lifecycle is not None else None)
        self.waker = (inference_session.Waker(self.lifecycle)
                      if inference_session is not None and self.lifecycle is not None else None)
        self.sweeps = 0
        self.last_sweep = None
        # Turns that streamed without a lease because the served model name matched no declared alias.
        self.unmanaged_streams = 0
        self.last_unmanaged = None
        # Stage 2: the generation this app last rebuilt at, so an idle tick costs one integer compare.
        # A generation counter cannot see another process's edits, so a slow reconciliation rebuild stays.
        self.runtime_generation = None
        self.runtime_skips = 0
        self.runtime_since_build = 0
        self.runtime_reconciles = 0
        # A short local answer can offer depth: "would you like me to delve deeper?" remembers the
        # original question, so agreeing sends *that* to the model rather than the word "yes".
        self.pending_deep = None
        self.offer_deepening = True
        self.daemon = self.make_daemon()

    def make_daemon(self):
        """Wire the engine to the banks it reasons over and to the two gates that already exist."""
        if daemon is None:
            return None
        banks: list[Path] = []
        if phases is not None and phases.available():
            banks += [path for _, path in phases.load_order()]
        banks += [APP_ROOT / "codex.aiml", APP_ROOT / "_override.aiml",
                  APP_ROOT / "aiml-en-us-foundation-alice" / "knumatic_learned.aiml"]
        return daemon.Daemon(kernel=self.kernel_reply, banks=[path for path in banks if path.is_file()],
                             admit=self.admit_verb, admit_plan=self.admit_plan,
                             admit_memory=self.admit_memory, admit_gitop=self.admit_gitop,
                             mode_of=lambda: self.mode)

    def kernel_reply(self, text: str) -> str:
        try:
            return str(self.router.respond(text) or "")
        except Exception:
            return ""

    def admit_verb(self, verb: str, argument: str) -> tuple[bool, str]:
        """The daemon may only select read-only verbs; the sandbox re-checks when it runs."""
        if verb not in {"git", "time", "files", "convert"}:
            return False, f"{verb} is not a read-only verb"
        if verb == "git":
            first = (shlex.split(argument) or ["status"])[0]
            allowed = ALLOWED_PROGRAMS.get("git", set())
            if first not in allowed:
                return False, f"git {first} is not on the allowlist"
        return True, f"read-only {verb}"

    def admit_plan(self, name: str) -> tuple[bool, str]:
        if planner is None:
            return False, "the planner is unavailable"
        # The payload is `<name> [<term>]`; only the first token names a plan.
        head = str(name).strip().lower().split()
        if not head:
            return False, "no plan name given"
        plan = planner.resolve(head[0])
        if not plan.admitted:
            return False, plan.problems[0] if plan.problems else "not admitted"
        if plan.authority != "execute":
            return False, f"admitted as {plan.authority}, so nothing may run"
        return True, f"plan {plan.name} admitted"

    def update_client(self, model: str | None = None):
        config = PROVIDER_CONFIGS[self.current_provider]
        self.model_name = model or config["default_model"]
        if self.current_provider is Provider.LLAMA_SERVER and self.model_name == "auto":
            # Whatever the server actually loaded wins; the configured default is the fallback.
            self.model_name = self.served_model() or DEFAULT_MODEL_ALIAS
        if config["base_url"]:
            self.client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
        else:
            self.client = OpenAI(api_key=config["api_key"])
        role = "local" if self.current_provider is Provider.LLAMA_SERVER else "advisor/cloud"
        self.sub_title = f"{role} · {self.current_provider.value} · {self.model_label()}"
        self.notify(f"Switched to {self.current_provider.value} · {self.model_label()}")

    def model_label(self) -> str:
        """The alias behind the id on the wire: llama-server advertises a full .gguf path, which is
        the id to send but a terrible thing to read in a title bar."""
        name = Path(str(self.model_name)).name
        for alias, target in MODEL_REGISTRY.items():
            if Path(target).name == name:
                return alias
        return self.model_name or "(none)"

    def served_model(self) -> str:
        """What llama-server actually loaded, or '' when it is not answering."""
        try:
            response = requests.get(LLAMA_ENDPOINT + "/v1/models", timeout=3)
            response.raise_for_status()
            models = response.json().get("data") or []
            if models:
                return str(models[0].get("id") or "")
        except (requests.RequestException, ValueError):
            return ""
        return ""

    def list_models(self) -> str:
        if not MODEL_REGISTRY:
            return "No models registered in gpt-oss.toml"
        served = self.served_model()
        lines = [f"Endpoint: {LLAMA_ENDPOINT}", f"Serving:  {served or '(nothing loaded)'}", ""]
        lines.append("   #  alias            tier         size   notes")
        for index, alias in enumerate(ordered_models(), start=1):
            path = model_path_for(alias)
            state = f"{path.stat().st_size / (1024 ** 3):5.2f} GB" if path.is_file() else "   ? GB"
            mark = "*" if alias == self.model_label() else " "
            notes = []
            if alias == DEFAULT_MODEL_ALIAS:
                notes.append("default")
            if not path.is_file():
                notes.append("MISSING")
            lines.append(f"{mark}{index:2}. {alias:<16} {tier_for(alias):<11} {state}   {', '.join(notes)}".rstrip())
        lines.append("")
        lines.append("fastest → deepest, top to bottom  ·  `/model <alias>` or Ctrl+P to switch")
        return "\n".join(lines)

    def get_semantic_router(self):
        """Learn the local AIML banks, most specific last.

        `_override.aiml` is the tool bridge (git, time, convert, files) and must win over anything
        generic; `knumatic_learned.aiml` is the dumper's output from past conversations; the corpus
        `startup.xml` is used only when it exists, which it does not in the ALICE tarball.
        """
        kernel = aiml.Kernel()
        # Knowledge first: python-aiml lets a later learn take precedence, so everything the daemon
        # owns (greetings, identity, memory, git) is learned after this and always wins.
        if knowledge is not None:
            for path in knowledge.paths():
                try:
                    kernel.learn(str(path))
                except Exception:
                    continue
        alice_dir = APP_ROOT / "aiml-en-us-foundation-alice"
        startup = alice_dir / "startup.xml"
        if alice_dir.is_dir() and startup.is_file():
            kernel.learn(str(startup))
        # K'UHUL phase banks first: lowest precedence, and only when their manifest digest matches.
        # They are data — the package grants no permission and this adds no second compiler.
        self.phase_note = ""
        if phases is not None and phases.available():
            loaded = 0
            for label, path in phases.load_order():
                if path.is_file():
                    try:
                        kernel.learn(str(path))
                        loaded += 1
                    except Exception as error:  # a bank that will not parse must not stop the app
                        self.phase_note += f"{label}: {error}; "
            self.phase_note = self.phase_note or f"{loaded} phase banks learned"
        learned = alice_dir / "knumatic_learned.aiml"
        if learned.is_file():
            kernel.learn(str(learned))
        # Reuse this exact python-aiml Kernel; no second parser/compiler.
        # Prefer the existing compiled corpus directory, with a root fallback.
        codex = alice_dir / "codex.aiml"
        if not codex.is_file():
            codex = APP_ROOT / "codex.aiml"
        if codex.is_file():
            kernel.learn(str(codex))
        memory_bank = APP_ROOT / "memory.aiml"
        if memory_bank.is_file():
            kernel.learn(str(memory_bank))
        identity = APP_ROOT / "identity.aiml"
        if identity.is_file():
            kernel.learn(str(identity))
        smalltalk = APP_ROOT / "smalltalk.aiml"
        if smalltalk.is_file():
            kernel.learn(str(smalltalk))
        git_bank = APP_ROOT / "gitops.aiml"
        if git_bank.is_file():
            kernel.learn(str(git_bank))
        compose_bank = APP_ROOT / "compose.aiml"
        if compose_bank.is_file():
            kernel.learn(str(compose_bank))
        override = APP_ROOT / "_override.aiml"
        if override.is_file():
            kernel.learn(str(override))
        kernel.setBotPredicate("name", "KNUMATIC")
        return kernel

    # -- the AIML side of the tool bridge ------------------------------------------------------------
    def run_tool_verb(self, verb: str, argument: str) -> str:
        """Execute what a `TOOL <verb> <args>` template asked for. Only verbs this file knows."""
        verb = (verb or "").strip().lower()
        argument = (argument or "").strip()
        if verb == "git":
            # run_command keeps its own allowlist and subcommand checks; this adds no power.
            return sandbox.run_command("git", shlex.split(argument) or ["status"])
        if verb == "files":
            return sandbox.list_dir(".")
        if verb == "time":
            stamp = datetime.now().strftime("%I:%M %p")
            return f"It's {stamp.lstrip('0')}."
        if verb == "convert":
            parts = argument.replace(",", " ").split()
            if len(parts) < 3:
                raise SandboxError("convert needs: <value> C F | <value> F C")
            value = float(parts[0])
            from_unit, to_unit = parts[1].upper(), parts[2].upper()
            if from_unit == to_unit:
                return f"{value:g}{from_unit}"
            if from_unit == "C" and to_unit == "F":
                result = value * 9 / 5 + 32
            elif from_unit == "F" and to_unit == "C":
                result = (value - 32) * 5 / 9
            else:
                raise SandboxError(f"cannot convert {from_unit} to {to_unit}")
            return f"{value:g}°{from_unit} is {result:.0f}°{to_unit}"
        raise SandboxError(f"unknown tool verb {verb!r}")

    @staticmethod
    def completion_registry() -> tuple[str, ...]:
        """Declarations from the typed registry, not a hand-written list.

        codex.aiml emits call forms like `read_file(path)`; the host now accepts one only if it is a
        registered contract (functions.declarations) or a declared plan. This still grants nothing:
        completion fills the input, it never dispatches.
        """
        if functions is None:
            return (
                "list_dir(path)", "read_file(path)", "run_command(program, args)",
                "git_command(command, arguments)", "search_history(query)",
                "write_file(path, content)", "patch_file(path, find, replace)",
            )
        declarations = list(functions.declarations())
        if planner is not None:
            declarations += [f"plan:{plan.name}" for plan in planner.load().values()]
        return tuple(declarations)

    def suggest_completion(self, text: str) -> str:
        """Existing AIML/SRAI brain -> validated suggestion -> mu.py rank/closure."""
        if not text.strip() or self.completion is None:
            return ""
        # Only the last phrase is queried; no input is executed or submitted.
        phrase = text.strip().lstrip("/").replace("_", " ")
        if len(phrase) > 160:
            return ""
        try:
            reply = str(self.router.respond(phrase.upper()) or "").strip()
        except Exception:
            return ""
        if not reply.startswith("CODEX_SUGGEST "):
            return ""
        _, _, payload = reply.partition(" ")
        kind, _, suggestion = payload.partition(" ")
        if not suggestion:
            return ""
        if kind == "function":
            # Reject names not declared by the active host. This does not grant access.
            if suggestion not in self.completion_registry():
                return ""
            if suggestion.startswith(("write_file", "patch_file")) and not sandbox.allow_write:
                return ""
            ctx = self.completion.complete(suggestion.split("(")[0], mode="code", source="sandbox", workspace=sandbox.root)
            if suggestion not in [candidate.text for candidate in ctx.candidate_functions]:
                return ""
        elif kind not in {"command", "sentence", "question"}:
            return ""
        return suggestion

    @on(Input.Changed)
    def update_completion(self, event: Input.Changed) -> None:
        self.current_completion = self.suggest_completion(event.value)
        try:
            self.query_one("#completion-hint", Static).update(
                f"Ctrl+Space → {self.current_completion}" if self.current_completion else ""
            )
        except Exception:
            pass

    def action_accept_completion(self) -> None:
        """Fill input only. Never dispatch a tool or submit a chat turn."""
        if not self.current_completion:
            return
        field = self.query_one(Input)
        field.value = self.current_completion
        field.cursor_position = len(field.value)
        self.current_completion = ""

    def plan_answer(self, payload: str) -> str:
        """`CODEX_PLAN <name> [<term>]`, `CODEX_PLAN run <name> [<term>]` or `CODEX_PLAN registry`.

        The AIML bank only ever *proposes* this; admission is the planner's call: every step must be
        a registered, implemented function whose types chain.
        """
        if functions is None or planner is None:
            return "the typed registry is unavailable in this environment"
        head, _, rest = payload.partition(" ")
        head, rest = head.strip(), rest.strip()
        if head.lower() in {"registry", "list", ""}:
            return functions.describe()
        if head.lower() in {"run", "proposal"}:
            head, _, rest = rest.partition(" ")
            head, rest = head.strip(), rest.strip()
        # AIML upper-cases everything it matches, and plan names are lowercase in plans.toml.
        plan = planner.resolve(head.lower())
        blocks = [f"plan **{plan.name}** — {plan.title}"]
        if plan.steps:
            blocks.extend(["```", plan.diagram(), "```"])
        if not plan.admitted:
            blocks.append("**refused at admission:**")
            blocks.extend(f"- {problem}" for problem in plan.problems)
            blocks.append("")
            blocks.append("A template may propose this; only a registered, implemented composition can run it.")
            return "\n".join(blocks)
        blocks.append(f"admitted · authority `{plan.authority}`")
        if plan.authority != "execute":
            blocks.append("Nothing was run: an admitted composition with no execution authority stays a proposal.")
            return "\n".join(blocks)
        ok, output = planner.run(plan, functions.ToolContext(Path(sandbox.root), sandbox), term=rest)
        blocks.append("**ran:**" if ok else "**stopped:**")
        blocks.extend(["```", output, "```"])
        return "\n".join(blocks)

    # -- user memory: proposals in, admitted writes out ---------------------------------------------
    def record_turn(self, text: str, *, kind: str, latency_ms: int, inference: str,
                    observed_execution: bool = False, execution_kind: str | None = None) -> dict | None:
        """Record one turn. Best effort: a recording failure never changes the answer or grants anything."""
        if evidence_record is None:
            return None
        try:
            record = evidence_record.build(
                input_text=text, request_id=self.request_id, latency_ms=latency_ms,
                inference=inference, observed_execution=observed_execution,
                execution_kind=execution_kind,
                routing=dict(action=self.last_routing.get("action") if self.last_routing else None,
                             closure=self.last_routing.get("closure") if self.last_routing else None),
                binding={"micronaut": "micronaut://v1/compose", "selected": None},
                operators=[])
            self.last_record = evidence_record.append(record)
            self.last_record_error = None
            return self.last_record
        except Exception as error:
            # Losing an observation is a defect; letting it break the turn would be a worse one.
            self.last_record_error = f"{type(error).__name__}: {error}"
            self.last_record = None
            return None

    def granted_capabilities(self) -> set[str]:
        """What this session may do, in capability terms the phase chain can name."""
        granted = {"graph.relations.read"}
        if user_memory is not None and (self.memory_write or user_memory.writable()):
            granted.add("memory.write")
        if self.git_write:
            granted.add("repo.write")
        if sandbox.allow_write:
            granted.add("file.write")
        return granted

    def phase_route(self, text: str) -> dict | None:
        """Consult the chain before answering. Returns the verdict, or None if unavailable."""
        if phase_routing is None:
            return None
        try:
            verdict = phase_routing.route(text, granted=self.granted_capabilities(),
                                          context={"user": self.user_id},
                                          request_id=getattr(self, "request_id", None))
        except Exception as error:  # a broken chain must not take the turn down
            self.last_routing = dict(action="fallback", reason=f"chain unavailable: {error}")
            return self.last_routing
        self.last_routing = verdict
        self.last_plan = verdict.get("plan")
        return verdict

    def action_plan(self, argument: str = "") -> None:
        """Show the phase chain's verdict for the last turn, or for a given text."""
        text = (argument or "").strip()
        verdict = self.phase_route(text) if text else self.last_routing
        if not verdict:
            self.say_system("No phase-chain verdict yet. `/plan <text>` resolves one.")
            return
        if phase_routing is not None:
            self.say_system("```\n" + phase_routing.summary(verdict) + "\n```")

    def admit_memory(self, kind: str, argument: str) -> tuple[bool, str]:
        """memquery is read-only; a memory write needs the grant, exactly like /allow."""
        if user_memory is None:
            return False, "the memory module is unavailable"
        if kind == "memquery":
            return True, "read-only graph projection query"
        granted = self.memory_write or user_memory.writable()
        if not granted:
            return False, "memory writes need `/allow memory` (or KNUMATIC_MEMORY_WRITE=1)"
        return True, "memory write granted"

    def admit_gitop(self, kind: str, argument: str) -> tuple[bool, str]:
        """Building reads; committing and pushing need the repo-write grant."""
        if gitops is None:
            return False, "the git operations module is unavailable"
        verb = (argument or "").split(" ")[0].strip().lower()
        if verb == "build":
            return True, "build is read-only (compile + suite)"
        if verb == "clone":
            if not sandbox.allow_write:
                return False, "cloning writes files into the workspace: `/allow` first"
            return True, "clone into the workspace is granted"
        if not self.git_write:
            return False, f"repo writes need `/allow git` (asked to {verb or 'modify'} the repository)"
        return True, f"repo write granted: {verb}"

    def execute_gitop(self, argument: str) -> str:
        """Run one admitted git operation and render exactly what ran and what came back."""
        if gitops is None:
            return "the git operations module is unavailable"
        verb, _, rest = (argument or "").strip().partition(" ")
        verb, rest = verb.strip().lower(), rest.strip()
        root = sandbox.root
        if verb == "clone":
            url, _, destination = rest.partition(" ")
            if not url.strip():
                return ("Give me the url: `/clone <https url> [directory]`, or ask the model to "
                        "`clone_repo`. Nothing was changed.")
            result = gitops.clone(url, destination.strip() or None, root=root)
        elif verb == "build":
            result = gitops.build(root)
        elif verb == "commit":
            result = gitops.commit(root, rest)
        elif verb == "push":
            result = gitops.push(root)
        elif verb == "sync":
            result = gitops.sync(root, rest)
        else:
            return f"unknown git operation `{verb}` - try commit, push, sync or build"
        status = "**ok**" if result["ok"] else f"**failed** (exit {result.get('exit_code')})"
        return f"{result['output']}\n\n{status}"

    def execute_compose(self, argument: str) -> str:
        """Retrieve, compose and verify a paragraph about one subject. Reads only."""
        if compose is None:
            return "the composition module is unavailable"
        subject = (argument or "").strip() or "pet"
        result = compose.paragraph(self.user_id, f"tell me about my {subject}", request_id=getattr(self, "request_id", None))
        if not result["ok"]:
            reasons = "; ".join(problem["detail"]
                               for problem in result["verification"]["problems"][:3])
            summary_text = (f"I cannot compose that yet: {reasons or result['plan'].get('reason')}. "
                            "Nothing was invented to fill the gap.")
        else:
            summary_text = compose.summary(result)
        # Xul closes the turn either way: a refusal to compose is still an emitted answer, and the trace says
        # whether the closure was a success.
        if phase_events is not None:
            request_id = getattr(self, "request_id", None)
            try:
                phase_events.emit(request_id, "phase_enter", phase="Xul", source="host",
                                  detail={"operation": "compose.summary", "ok": bool(result.get("ok"))})
                phase_events.emit(request_id, "phase_exit", phase="Xul", source="host",
                                  detail={"operation": "compose.summary", "ok": bool(result.get("ok")),
                                          "outcome": ("ok" if result.get("ok") else "failed"),
                                          "emitted": len(summary_text)})
            except Exception:
                pass
        return summary_text

    def action_compose(self, argument: str = "") -> None:
        self.say_system(self.execute_compose(argument))

    def execute_memory(self, kind: str, argument: str) -> str:
        """Run an admitted memory operation and say what happened, with the event id."""
        if user_memory is None:
            return "the memory module is unavailable"
        argument = (argument or "").strip()
        if kind == "memquery":
            subject, _, predicate = argument.partition(".")
            if not subject or not predicate:
                return "a memory query needs `<subject>.<predicate>`"
            return user_memory.answer(self.user_id, subject, predicate)
        verb, _, rest = argument.partition(" ")
        verb, rest = verb.strip().lower(), rest.strip()
        if verb == "erase":
            outcome = user_memory.erase(self.user_id)
            return (f"Erased {outcome['removed']} event(s) for **{outcome['user']}** and left a "
                    f"tombstone (`{outcome['tombstone']}`). History is append-only, so erasure compacts.")
        target, _, value = rest.partition(" ")
        subject, _, predicate = target.partition(".")
        if not subject or not predicate:
            return "a memory operation needs `<subject>.<predicate>`"
        if verb == "forget":
            record = user_memory.forget(user=self.user_id, subject=subject, predicate=predicate)
            return f"Retracted `{subject}.{predicate}` for **{self.user_id}** (`{record['event_id']}`)."
        if verb == "remember":
            record = user_memory.remember(user=self.user_id, subject=subject, predicate=predicate, value=value)
            return f"Recorded `{subject}.{predicate}` = **{value}** for **{self.user_id}** (`{record['event_id']}`)."
        return f"unknown memory operation `{verb}`"

    def action_serve(self, argument: str = "") -> None:
        """Start or stop the loopback endpoint. External clients get local answers, nothing more."""
        if micronaut_server is None:
            self.say_system("the server module is unavailable")
            return
        word = (argument or "").strip().lower()
        if word in {"off", "stop", "no"}:
            if self.server is not None:
                self.server.shutdown()
                self.server.server_close()
                self.server = None
                self.say_system("Endpoint stopped.")
            else:
                self.say_system("No endpoint was running.")
            return
        if self.server is not None:
            host, bound = self.server.server_address[:2]
            self.say_system(f"Already serving at {micronaut_server.transport(bound)}")
            return
        port = int(word) if word.isdigit() else micronaut_server.DEFAULT_PORT
        try:
            engine = micronaut_server.Engine(app=self)
            self.server = micronaut_server.serve(port, block=False, engine=engine)
        except OSError as error:
            self.say_system(f"**Could not bind port {port}:** {error}")
            return
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        host, bound = self.server.server_address[:2]
        self.say_system(
            f"Serving on **{micronaut_server.transport(bound)}** (logical `{micronaut_server.uri()}`).\n\n"
            "External clients get local answers only: no model calls, no memory writes, no git. "
            "`/serve off` stops it."
        )

    def action_clone(self, argument: str = "") -> None:
        """Clone an https repo into the workspace. It writes files, so it needs `/allow`."""
        if gitops is None:
            self.say_system("the git operations module is unavailable")
            return
        if not sandbox.allow_write:
            self.say_system("**Not authorized** - cloning writes files into the workspace. "
                            "`/allow` first, then `/clone <https url> [dir]`. Nothing was changed.")
            return
        url, _, destination = (argument or "").strip().partition(" ")
        outcome = gitops.clone(url, destination.strip() or None, root=sandbox.root)
        if outcome["ok"]:
            self.say_system(f"Cloned into **{outcome['path']}** ({outcome.get('branch')} @ "
                            f"{outcome.get('head')}).\n\n{outcome['output']}")
            self.refresh_workspace_bar()
        else:
            self.say_system(f"**Clone failed**{' (refused)' if outcome.get('refused') else ''}:\n\n"
                            f"{outcome['output']}")

    def action_gitop(self, verb: str, argument: str = "") -> None:
        admitted, why = self.admit_gitop("gitop", f"{verb} {argument}".strip())
        if not admitted:
            self.say_system(f"**Not authorized** - {why}. Nothing was changed.")
            return
        self.say_system(self.execute_gitop(f"{verb} {argument}".strip()))

    def action_git_grant(self, argument: str = "") -> None:
        word = (argument or "").strip().lower()
        self.git_write = word not in {"off", "no", "read", "readonly", "read-only", "false"}
        self.say_system(f"Repository writes (commit, push): "
                        f"{'granted' if self.git_write else 'revoked'}.")

    def action_build(self) -> None:
        self.say_system(self.execute_gitop("build"))

    def identity_text(self) -> str:
        """Who this is: the daemon, its phases, the models it can reach, and its mark."""
        models = []
        for alias in ordered_models():
            path_for_alias = model_path_for(alias)
            size = f"{path_for_alias.stat().st_size / (1024 ** 3):.2f} GB" if path_for_alias.is_file() else "missing"
            mark = "*" if alias == DEFAULT_MODEL_ALIAS else " "
            models.append(f"  {mark}{alias:<16} {tier_for(alias):<10} {size}")
        advisors = ", ".join(
            f"{provider.value}{'' if PROVIDER_CONFIGS[provider]['api_key'] else ' (no key)'}"
            for provider in ADVISOR_ENV)
        # The mark, drawn the same way the header draws it (logo.png at 20x20 -> 10 art rows).
        mark = ""
        if png_logo is not None:
            try:
                mark = png_logo.load_default().render(20, 20).plain
            except Exception:
                mark = ""
        lines = [
            "I am a **Micronaut Daemon Bot** — a local, six-phase terminal agent. Not ALICE: the ALICE",
            "corpus is vendored data I can learn patterns from, not who I am.",
            "",
            "Phases: Pop → Wo → Yax → Sek → Ch'en → Xul — every turn runs all six, and `/daemon`",
            "shows the trace of the last one.",
            f"Serving: **{self.model_label()}** via {self.current_provider.value}"
            + (f" · mode {self.mode}" if self.mode else " · no mode set"),
            "",
            "Models I can talk to (fastest → deepest, * marks the default):",
            *models,
            "",
            f"Advisors, if you want a second opinion: {advisors}",
        ]
        if mark:
            lines += ["", "My mark (the header animates this vector):", "```", mark, "```"]
        return "\n".join(lines)

    def memory_summary(self) -> str:
        if user_memory is None:
            return "The memory module is unavailable."
        facts = user_memory.projection(self.user_id)
        document = user_memory.graph(self.user_id)
        check = user_memory.validate(document)
        lines = [f"user: **{self.user_id}** · writes: {'granted' if (self.memory_write or user_memory.writable()) else 'read-only'}"]
        if not facts:
            lines.append("nothing remembered yet — say \"my dog's name is Max\"")
        for subject in sorted(facts):
            for predicate in sorted(facts[subject]):
                lines.append(f"  {subject}.{predicate} = {facts[subject][predicate]}")
        lines.append("")
        lines.append(f"graph projection: {check['nodes']} node(s), {check['edges']} edge(s), "
                     f"schema {'valid' if check['ok'] else 'INVALID'} ({', '.join(check['fields'][:4])}…)")
        for problem in check["problems"][:4]:
            lines.append(f"  {problem['code']}: {problem['detail']}")
        lines.append("")
        lines.append("`/user <id>` switches identity · `/allow memory` grants writes · `/allow memory off` revokes")
        return "\n".join(lines)

    def action_links(self, argument: str = "") -> None:
        if links is None:
            self.say_system("the links module is unavailable")
            return
        query = (argument or "").strip()
        if not query:
            self.say_system("Give me a topic: `/links saturn`, `/links quantum chromodynamics`.")
            return
        block = links.block(query, limit=6, heading=f"Reference links for {query}")
        self.say_system(block or f"no reference links for {query!r}")

    def lease(self, model: str):
        """A context manager that holds one lease; anything raised inside still releases it."""
        if self.lifecycle is None:
            class _Noop:
                def __enter__(self_inner): return None
                def __exit__(self_inner, *exc): return False
            return _Noop()

        class _Lease:
            def __enter__(self_inner):
                self_inner.info = self.lifecycle.acquire(model)
                return self_inner.info

            def __exit__(self_inner, *exc):
                self.lifecycle.release(model)
                return False

        return _Lease()

    def sweep_idle(self) -> None:
        """The tick: stop owned, unleased backends past their idle budget. Never starts anything."""
        if self.lifecycle is None:
            return
        self.sweeps += 1
        try:
            self.last_sweep = self.lifecycle.release_idle()
        except Exception as error:
            self.last_sweep = dict(error=f"{type(error).__name__}: {error}")

    def poll_runtime(self) -> None:
        """Stage 1 reactive projection: poll, compare a semantic digest, render only on change.

        Read-only by construction: `runtime_tree.watch()` builds the projection from the registries and
        calls nothing that could wake a model, take a lease or change a binding.
        """
        if runtime_tree is None:
            return
        self.runtime_polls += 1
        if runtime_signals is not None:
            generation = runtime_signals.generation()
            if generation == self.runtime_generation and self.runtime_since_build < RECONCILE_EVERY:
                self.runtime_skips += 1
                self.runtime_since_build += 1
                return
            if generation == self.runtime_generation:
                self.runtime_reconciles += 1     # the fallback: re-read the registries anyway
            self.runtime_generation = generation
        self.runtime_since_build = 0
        try:
            view = (model_lifecycle.observed(self.lifecycle)
                    if model_lifecycle is not None and self.lifecycle is not None else None)
            snapshot = runtime_tree.watch(lifecycle_view=view)
        except Exception as error:            # a broken registry is displayed, never fatal
            self.runtime_digest = f"error:{type(error).__name__}"
            return
        if snapshot["digest"] == self.runtime_digest:
            return
        self.runtime_digest = snapshot["digest"]
        self.runtime_renders += 1
        self.last_tree = snapshot["tree"]
        try:
            panel = self.query_one("#green-screen", Static)
        except Exception:
            return
        tree = snapshot["tree"]
        models = ", ".join(f"{node['id'].split('/')[-1]} {node['fields'].get('state', '?')}"
                           for node in tree["nodes"] if node["kind"] == "model")
        counts = " · ".join(f"{kind} {count}" for kind, count in snapshot["counts"].items())
        panel.update(f"{len(tree['nodes'])}n/{len(tree['edges'])}e · {counts}\n{models}")

    def on_mount(self) -> None:
        self.set_interval(2.0, self.poll_runtime)
        self.set_interval(30.0, self.sweep_idle)

    def action_profile(self) -> None:
        """Show the local profile for this user, and say plainly that it grants nothing."""
        if user_profile is None:
            self.say_system("The profile store (profile.py) is unavailable.")
            return
        loaded = user_profile.load(self.user_id)
        self.say_system(user_profile.summary(loaded))
        view = user_profile.read_for_answer(self.user_id)
        if view["shareable"]:
            self.say_system("shareable: " + json.dumps(view["shareable"], sort_keys=True))
        if view["bindings"]:
            self.say_system("bindings: " + json.dumps(view["bindings"], sort_keys=True))
        if not loaded["ok"]:
            for problem in loaded["problems"]:
                self.say_system(f"refused · {problem['code']}: {problem['detail']}")
        self.say_system("A profile is configuration: it can steer what I say, never what I am allowed to do. "
                        "Tokens and capabilities do not belong in it, and are refused.")

    def action_runtime(self) -> None:
        """The runtime projection: what the registries actually say about the running system."""
        if runtime_tree is None:
            self.say_system("The runtime projection (runtime_tree.py) is unavailable.")
            return
        try:
            tree = runtime_tree.projection()
        except Exception as error:
            self.say_system(f"The runtime projection could not be built: {type(error).__name__}: {error}")
            return
        self.last_tree = tree
        for line in runtime_tree.render(tree).splitlines():
            self.say_system(line)

    def action_evidence(self) -> None:
        """What the recorder saw on the last turn, and whether the log still verifies."""
        if evidence_record is None:
            self.say_system("The evidence recorder (evidence_record.py) is unavailable.")
            return
        record = self.last_record
        if record is None:
            self.say_system(f"Last turn: not recorded ({self.last_record_error or 'no turn yet'}).")
        else:
            self.say_system(
                f"Last turn `{record['request_id'] or '-'}` · inference {record['inference'] or '-'} · "
                f"{record['latency_ms']} ms · executed {record['observed_execution']} · "
                f"admitted {record['admission']['proposal_admitted']}")
        rows = evidence_record.load()
        report = evidence_record.verify()
        self.say_system(f"Evidence log · {len(rows)} record(s) · chain "
                        f"{'verified' if report['ok'] else 'BROKEN'} · {evidence_record.LOG}")
        if phase_events is not None:
            trace = phase_events.observe(self.request_id or "")
            self.say_system(phase_events.summary(trace) +
                            ("" if trace.get("observed") else " · no phase events were observed"))

    def action_memory(self) -> None:
        self.say_system(self.memory_summary())

    def action_memory_grant(self, argument: str = "") -> None:
        word = (argument or "").strip().lower()
        self.memory_write = word not in {"off", "no", "read", "readonly", "read-only", "false"}
        self.say_system(f"Memory writes: {'granted' if self.memory_write else 'revoked'} for **{self.user_id}**.")

    def action_phases(self) -> None:
        """Verify the K'UHUL package as data: digests, cycle order, and what precedence will do."""
        if phases is None:
            self.say_system("The K'UHUL phase adapter (phases.py) is unavailable.")
            return
        report = phases.summary([APP_ROOT / "codex.aiml", APP_ROOT / "_override.aiml"])
        note = getattr(self, "phase_note", "")
        self.say_system((f"loader: {note}\n\n" if note else "") + report)

    def action_gml(self) -> None:
        """What the base's GML extension declares right now, and whether its documents hold up."""
        if phases is None or functions is None:
            self.say_system("The phase adapter or the function registry is unavailable.")
            return
        entry = functions.get("gml_validate")
        verdicts = "validation unavailable"
        if entry is not None and entry.handler is not None:
            contracts = phases.ROOT / "contracts"
            files = [{"path": path.relative_to(APP_ROOT).as_posix()} for path in sorted(contracts.glob("*.gml"))]
            try:
                rows = entry.handler(functions.ToolContext(APP_ROOT, sandbox), files)
                states: dict[str, int] = {}
                for row in rows:
                    states[row["state"]] = states.get(row["state"], 0) + 1
                verdicts = " · ".join(f"{state} {count}" for state, count in sorted(states.items())) or "no documents"
            except Exception as error:
                verdicts = f"validation failed: {error}"
        self.say_system(f"{phases.base_health()}\n\n{phases.extension_summary()}\n\ncontracts: {verdicts}")

    def action_plans(self) -> None:
        """List every declared plan and whether the registry admits it."""
        if planner is None:
            self.say_system("The plan composer is unavailable in this environment.")
            return
        plans = planner.load()
        if not plans:
            self.say_system("No plans declared in plans.toml.")
            return
        lines = ["Plans from `plans.toml`, resolved against the registry:", ""]
        for plan in plans.values():
            state = "admitted" if plan.admitted else "refused"
            lines.append(f"- `{plan.name}` · {plan.authority} · {state} · {plan.chain()}")
            for problem in plan.problems:
                lines.append(f"    - {problem}")
        lines.append("")
        lines.append("`/plan <name> [term]` shows the graph; `/plan run <name> [term]` runs an admitted one.")
        self.say_system("\n".join(lines))

    def maybe_reference(self, answer: str, *, last_user: str, response) -> str:
        """Append reference links to a model answer that has none - and never to a non-topic."""
        if links is None or not answer.strip() or links.has_links(answer):
            return answer
        try:
            routes = greetings.routes(last_user) if greetings is not None else None
        except Exception:
            routes = None
        intents = (routes or {}).get("intents") or []
        if not intents or intents[0].get("destination") != "question":
            return answer
        extra = links.block(last_user)
        if not extra:
            return answer
        response.update(f"\n\n{extra}")
        return f"{answer}\n\n{extra}"

    def _maybe_offer(self, question: str, answer: str) -> str:
        """Attach the deepening offer to a short factual answer, remembering the original question."""
        if not self.offer_deepening or greetings is None or not (answer or "").strip():
            return answer
        try:
            routes = greetings.routes(question)
        except Exception:
            return answer
        intents = routes.get("intents") or []
        if len(intents) != 1 or intents[0].get("destination") != "question":
            return answer
        self.pending_deep = question
        references = links.block(question) if links is not None else ""
        parts = [answer]
        if references:
            parts.append(references)
        parts.append("_Would you like me to delve deeper into it? Say **yes** and I will ask "
                     "the model about your original question._")
        return "\n\n".join(parts)

    def multi_intent_answer(self, text: str, _depth: int = 0) -> str | None:
        """Answer a multi-intent utterance from the graph, or hand the whole thing on.

        "Hey, how are you, and what is the time?" is three intents. The bank would answer the greeting
        and drop the rest, so each clause is routed through greeting.gml and answered; if any clause
        cannot be answered locally, the whole utterance takes the normal path - half an answer is
        worse than an honest handoff.
        """
        if greetings is None or _depth > 0:
            return None
        try:
            routes = greetings.routes(text)
        except Exception:
            return None
        if not routes.get("multi"):
            return None
        parts = []
        for intent in routes["intents"]:
            local = self.local_answer(intent["clause"], _depth=_depth + 1) if intent["clause"] else None
            if local is None:
                return None
            kind, body = local
            parts.append(f"**{intent['destination']}** — {body}")
        return "\n\n---\n\n".join(parts)

    def local_answer(self, text: str, _depth: int = 0) -> tuple[str, str] | None:
        """The daemon runs one cycle per turn; its closure decides, or defers to the model.

        Pop/Wo/Yax/Sek/Ch'en/Xul are recorded on `self.last_turn` (see `/daemon`). The engine can
        only ever *propose* a read-only verb or an admitted plan; the execution below is the same
        code path the model's tools use.
        """
        verdict = self.phase_route(text) if _depth == 0 else None
        if verdict is not None and verdict.get("action") == "refuse":
            # An execution-class capability is required and not granted. No fallback: falling back
            # would run the same operation through the unrestricted path the grant exists to gate.
            return "refused", verdict["reason"]
        combined = self.multi_intent_answer(text, _depth)
        if combined:
            return "aiml", combined
        if self.daemon is None:
            return self._local_answer_direct(text)
        turn = self.daemon.run(text)
        self.last_turn = turn
        if turn.kind == "deferred":
            return None
        if turn.kind == "mode":
            self.action_set_mode(turn.mode)
            info = daemon.modes().get(turn.mode) if daemon is not None else None
            detail = f"\n\n{info.vector()}" if info else ""
            return "mode", f"Response mode is now **{turn.mode}**{detail}"
        if turn.kind == "tool":
            verb, _, argument = turn.answer.partition(" ")
            try:
                return "tool", self.run_tool_verb(verb, argument)
            except Exception as error:
                return "error", str(error)
        if turn.kind == "plan":
            return "plan", self.plan_answer(turn.answer)
        if turn.kind in {"memory", "memquery"}:
            return turn.kind, self.execute_memory(turn.kind, turn.answer)
        if turn.kind == "identity":
            return "aiml", self.identity_text()
        if turn.kind == "refused":
            # A refusal is an answer: the user is told what to fix, not handed to the model.
            return "refused", turn.answer
        if turn.kind == "aiml":
            return "aiml", self._maybe_offer(text, turn.answer)
        if turn.kind == "gitop":
            return "gitop", self.execute_gitop(turn.answer)
        if turn.kind == "compose":
            return "compose", self.execute_compose(turn.answer)
        return "aiml", turn.answer

    def _local_answer_direct(self, text: str) -> tuple[str, str] | None:
        """The pre-daemon path, kept for the case where daemon.py is absent."""
        try:
            reply = (self.router.respond(text.upper()) or "").strip()
        except Exception:
            reply = ""
        if not reply or "__LLM_FALLBACK__" in reply:
            return None
        if reply.upper().startswith("CODEX_PLAN "):
            return "plan", self.plan_answer(reply[len("CODEX_PLAN "):].strip())
        if reply.startswith(("CODEX_SUGGEST ", "CODEX_LOOKUP ")):
            return None
        if reply.upper().startswith("TOOL "):
            verb, _, argument = reply[5:].partition(" ")
            try:
                return "tool", self.run_tool_verb(verb, argument)
            except Exception as error:
                return "error", str(error)
        return "aiml", reply

    # -- daemon modes and the cycle trace ----------------------------------------------------------
    def action_set_mode(self, name: str) -> str:
        """Switch the response-mode bias vector. The mode is style, never permission."""
        self.mode = (name or "").strip().lower()
        self.refresh_system_prompt()
        return self.mode

    def action_modes(self) -> None:
        if daemon is None:
            self.say_system("The daemon engine (daemon.py) is unavailable.")
            return
        current = f"current: **{self.mode}**\n\n" if self.mode else ""
        self.say_system(current + daemon.describe_modes())

    def action_daemon(self) -> None:
        """Show the last turn's six phases: what each one saw and decided."""
        if self.last_turn is None:
            self.say_system("No turn has run through the daemon engine yet. Ask something first.")
            return
        self.say_system("```\n" + self.last_turn.trace() + "\n```")

    def get_commands(self) -> dict[str, tuple[str, Callable[[], object], str]]:
        """Ctrl+P and `/commands`: local models first (fastest to deepest), then advisors."""
        commands: dict[str, tuple[str, Callable[[], object], str]] = {}
        for alias in ordered_models():
            commands[f"model:{alias}"] = (
                f"Model: {alias} ({tier_for(alias)})",
                partial(self.action_use_model, alias),
                f"Local, served by runtime/llama: {MODEL_REGISTRY[alias]}",
            )
        for alias in ordered_models():
            mark = " (default)" if alias == DEFAULT_MODEL_ALIAS else ""
            commands[f"default:{alias}"] = (
                f"Default: {alias} ({tier_for(alias)}){mark}",
                partial(self.action_set_default, alias),
                f"Start with {alias} next time — writes gpt-oss.toml",
            )
        commands["models"] = ("Models: list local models", self.action_models, "Every alias, fastest first")
        commands["plan"] = ("Plan: list the declared compositions", self.action_plans, "Admitted only from the typed registry")
        commands["chain"] = ("Chain: the phase-chain verdict for a turn", self.action_plan, "Matches, redirects, capabilities and the fallback reason")
        commands["phase"] = ("Phase: verify the K'UHUL phase banks", self.action_phases, "Digests, cycle order and precedence")
        commands["serve"] = ("Serve: loopback endpoint for micronaut://v1/chat", self.action_serve, "Local answers only; no model, no writes")
        commands["clone"] = ("Git: clone an https repo into the workspace", self.action_clone, "Writes files: needs `/allow` first")
        commands["build"] = ("Build: compile the tree and run the package suite", self.action_build, "Read-only; no commit, no push")
        commands["commit"] = ("Git: commit the working tree", partial(self.action_gitop, "commit"), "Needs `/allow git` first")
        commands["push"] = ("Git: push the current branch", partial(self.action_gitop, "push"), "Needs `/allow git`; shows git's own error")
        commands["sync"] = ("Git: commit then push", partial(self.action_gitop, "sync"), "Commit, then push; stops at the first failure")
        commands["allow_git"] = ("Git: grant repo writes", partial(self.action_git_grant, "on"), "Enables commit and push until revoked")
        commands["links"] = ("Links: reference searches for a topic", self.action_links, "Wikipedia, Britannica, NASA, Space.com - searches, not pages I read")
        commands["memory"] = ("Memory: what is remembered about this user", self.action_memory, "JSONL history, GML projection, write grant")
        commands["allow_memory"] = ("Memory: grant writes", partial(self.action_memory_grant, "on"), "Facts may be recorded; erasure always allowed")
        commands["profile"] = ("Profile: what the bot may know about you", self.action_profile, "Configuration only; no capabilities, no secrets")
        commands["runtime"] = ("Runtime: the green-screen projection", self.action_runtime, "Read-only tree of phases, micronauts, models and evidence")
        commands["evidence"] = ("Evidence: the recorded turns and the chain state", self.action_evidence, "Request id, latency, execution vs admission; hash-chained")
        commands["gml"] = ("GML: what the tensor extension declares", self.action_gml, "Fields, constraints, and whether the documents validate")
        commands["mode"] = ("Mode: list the daemon response modes", self.action_modes, "Bias vectors as a style prior")
        commands["daemon"] = ("Daemon: trace the last turn's six phases", self.action_daemon, "What each phase saw and decided")
        commands["workspace"] = ("Workspace: pick the folder the model may edit", self.action_pick_workspace, f"Currently {sandbox.root}")
        commands["allow"] = ("Workspace: grant write and patch", partial(self.action_allow, "on"), "The model may change files here")
        commands["readonly"] = ("Workspace: back to read-only", partial(self.action_allow, "off"), "Reads and searches only")
        commands["sessions"] = ("Session: list past sessions", self.action_sessions, "Resume or rewind from here")
        commands["resume"] = ("Session: resume the most recent", self.action_resume, "Load the last conversation back in")
        commands["rewind"] = ("Session: rewind one exchange", partial(self.action_rewind, "1"), "Drop the last question and answer")
        commands["new_session"] = ("Session: start a new one", self.action_new_session, "Fresh transcript, same app")
        commands["keys"] = ("Keys: where to get each API key", self.action_keys, "OpenAI, DeepSeek, Claude, Ollama — with links")
        for provider, (label, url) in KEY_PAGES.items():
            commands[f"get_key:{provider.value}"] = (
                f"Get key: {label}",
                partial(self.action_open_key, provider),
                f"Opens {url} in the browser",
            )
        commands["switch_llama"] = ("Local: llama-server (default)", partial(self.action_switch, Provider.LLAMA_SERVER), f"{LLAMA_ENDPOINT}, no keys needed")
        commands["switch_ollama"] = ("Local: Ollama daemon", partial(self.action_switch, Provider.OLLAMA), "localhost:11434, if you run one")
        for provider, label in (
            (Provider.OPENAI, "OpenAI gpt-4o"),
            (Provider.DEEPSEEK, "DeepSeek chat"),
            (Provider.ANTHROPIC, "Claude sonnet-5-5"),
        ):
            token = ADVISOR_ENV[provider]
            commands[f"advisor_{provider.value}"] = (
                f"Advisor: {label} (cloud)",
                partial(self.action_switch, provider),
                f"{token} loaded from .env" if PROVIDER_CONFIGS[provider]["api_key"] else f"no {token} yet - /keys shows where to get one",
            )
        commands["task"] = ("Tasks: /task <description>", self.action_task_help, "Add or manage tasks in the TASKS panel")
        commands["task_list"] = ("Tasks: show list", partial(self.task_command, "list"), "Display tasks")
        commands["task_done"] = ("Tasks: mark done", partial(self.task_command, "done"), "Usage: /task done <number>")
        commands["task_start"] = ("Tasks: start", partial(self.task_command, "start"), "Usage: /task start <number>")
        commands["task_block"] = ("Tasks: block", partial(self.task_command, "block"), "Usage: /task block <number>")
        commands["clear"] = ("Chat: clear", self.action_clear, "Drop the conversation, keep the system prompt")
        return commands

    def action_task_help(self) -> None:
        self.say_system(
            "Tasks: `/task <description>` adds a task. "
            "Use `/task list`, `/task done N`, `/task start N`, "
            "`/task block N`, or `/task priority high N`. "
            "Numbers must be supported by the installed task-list backend."
        )

    def task_command(self, argument: str) -> None:
        """Route task commands through the installed TaskListBus, never a UI-only list."""
        argument = argument.strip()
        if not argument:
            self.action_task_help()
            return
        if not self.bus:
            self.say_system("Task list is unavailable (`task_list.py` not loaded).")
            return
        verb, _, remainder = argument.partition(" ")
        verb = verb.lower()
        remainder = remainder.strip()
        if verb in {"list", "ls"} and not remainder:
            bus_text = "task list"
        elif verb in {"done", "start", "block", "unblock", "remove"}:
            if not remainder:
                self.say_system(f"Usage: `/task {verb} <task number, ID, or title>`")
                return
            bus_text = f"{verb} task {remainder}"
        elif verb == "priority":
            level, _, number = remainder.partition(" ")
            if level.lower() not in {"high", "medium", "low"} or not number.strip():
                self.say_system("Usage: `/task priority high|medium|low <task number, ID, or title>`")
                return
            bus_text = f"priority {level.lower()} {number.strip()}"
        elif verb in {"clear", "clear_done", "clear_all"}:
            bus_text = "clear done" if remainder == "done" or verb == "clear_done" else "clear tasks" if remainder == "all" or verb == "clear_all" else ""
            if not bus_text:
                self.say_system("Usage: `/task clear done|all`")
                return
        else:
            bus_text = f"add task {argument}"
        try:
            outcome = self.bus.apply(bus_text)
            if not isinstance(outcome, dict):
                self.say_system("Task backend returned an unexpected response.")
                return
            reply = str(outcome.get("reply") or "Task backend did not return a message.")
            self.say_system(f"**[Tasks]**\n\n{reply}")
            if outcome.get("ok"):
                self.render_tasks(self.bus.snapshot())
        except Exception as error:
            self.say_system(f"Task command failed: {error}")

    def add_task(self, title: str) -> None:
        """Compatibility entry point for the legacy backslash task shortcut."""
        self.task_command(title)

    def handle_command(self, text: str) -> None:
        """`/models`, `/model <alias>`, `/advisor <name>`, or any key from get_commands()."""
        name, _, argument = text[1:].partition(" ")
        name, argument = name.strip().lower(), argument.strip()
        if name == "task":
            self.task_command(argument)
            return
        if name in {"model", "models"}:
            if argument:
                self.action_use_model(argument)
            else:
                self.action_models()
            return
        if name in {"local", "llama"}:
            self.action_switch(Provider.LLAMA_SERVER)
            return
        if name == "advisor":
            key = f"advisor_{argument.lower()}"
            commands = self.get_commands()
            if key in commands:
                commands[key][1]()
            else:
                names = ", ".join(f"`{provider.value}`" for provider in ADVISOR_ENV)
                self.say_system(
                    f"Advisors are the cloud second opinions: {names}.\n\n"
                    "`/advisor <name>` switches to one, `/keys` shows where each key comes from, "
                    "`/local` returns to the local server."
                )
            return
        if name == "default":
            self.action_set_default(argument or None)
            return
        if name in {"sessions", "history"}:
            self.action_sessions()
            return
        if name == "resume":
            self.action_resume(argument)
            return
        if name in {"rewind", "back"}:
            self.action_rewind(argument)
            return
        if name in {"new", "new_session"}:
            self.action_new_session()
            return
        if name == "plan":
            if argument:
                self.say_system(self.plan_answer(argument))
            else:
                self.action_plans()
            return
        if name in {"phase", "phases"}:
            self.action_phases()
            return
        if name in {"gml", "tensor"}:
            self.action_gml()
            return
        if name == "serve":
            self.action_serve(argument or "")
            return
        if name == "clone":
            self.action_clone(argument or "")
            return
        if name in {"build", "compile"}:
            self.action_build()
            return
        if name in {"commit", "push", "sync"}:
            self.action_gitop(name, argument or "")
            return
        if name == "links":
            self.action_links(argument or "")
            return
        if name in {"chain", "routing"}:
            self.action_plan(argument or "")
            return
        if name in {"memory", "remembered"}:
            self.action_memory()
            return
        if name == "user":
            if argument:
                self.user_id = argument.strip()
                self.action_memory()
            else:
                self.say_system(f"Current memory identity: **{self.user_id}**. `/user <id>` switches.")
            return
        if name in {"mode", "modes"}:
            if argument:
                mode = self.action_set_mode(argument)
                info = daemon.modes().get(mode) if daemon is not None else None
                if info is None:
                    self.say_system(f"No mode `{mode}` is declared. `/mode` lists them.")
                    return
                self.say_system(f"Response mode: **{info.name}**\n\n{info.vector()}\n\nStyle only — permissions do not change.")
            else:
                self.action_modes()
            return
        if name in {"daemon", "trace"}:
            self.action_daemon()
            return
        if name in {"workspace", "cwd"}:
            if argument:
                self.action_set_workspace(argument)
            else:
                self.action_pick_workspace()
            return
        if name in {"allow", "writes", "edit"}:
            if (argument or "").strip().lower().startswith("memory"):
                self.action_memory_grant((argument or "").replace("memory", "", 1) or "on")
            else:
                self.action_allow(argument or "on")
            return
        if name in {"readonly", "read-only"}:
            self.action_allow("off")
            return
        commands = self.get_commands()
        if name in commands:
            commands[name][1]()
            return
        known = ", ".join(f"/{key}" for key in commands)
        self.say_system(f"Unknown command `/{name}`. Known: {known}")

    def say_system(self, markdown: str) -> None:
        """Mount a system-log block in the chat view; only the app thread may touch widgets."""
        view = self.query_one("#chat-view", VerticalScroll)
        view.mount(ToolLog(markdown))
        view.scroll_end(animate=False)

    def action_switch(self, p):
        if p in CLOUD_PROVIDERS and not PROVIDER_CONFIGS[p]["api_key"]:
            label, url = KEY_PAGES[p]
            self.say_system(
                f"**{p.value}** is an advisor and needs a token.\n\n"
                f"- Get one: [{label}]({url})\n"
                f"- Save it: `{ADVISOR_ENV[p]}=...` in `{APP_ROOT / '.env'}` — start.bat offers to write it — then restart the app.\n\n"
                "The local server keeps answering meanwhile."
            )
            return
        self.current_provider = p
        self.update_client()

    def keys_table(self) -> str:
        """Every provider's key page as a markdown link, with the state of what is already set."""
        lines = ["Where each credential comes from:", ""]
        for provider, (label, url) in KEY_PAGES.items():
            if provider in ADVISOR_ENV:
                state = " · key set" if PROVIDER_CONFIGS[provider]["api_key"] else " · no key yet"
            else:
                state = " · no key needed"
            lines.append(f"- **{provider.value}** — [{label}]({url}){state}")
        lines.append("")
        lines.append("`Ctrl+click` opens a link, or use the palette's `Get key:` entries to launch the browser.")
        lines.append("Saved keys live in `.env` (gitignored); `start.bat advisor` writes them for you.")
        return "\n".join(lines)

    def action_keys(self) -> None:
        self.say_system(self.keys_table())

    def action_open_key(self, provider: Provider) -> None:
        """Open the provider's key page in the default browser — the click-through path."""
        label, url = KEY_PAGES[provider]
        try:
            opened = webbrowser.open(url, new=2)
        except Exception:
            opened = False
        if opened:
            self.say_system(f"Opened [{label}]({url}) in your browser.")
        else:
            self.say_system(f"No browser came up, so paste this yourself:\n\n[{label}]({url})")

    def action_set_default(self, alias: str | None = None) -> None:
        """Persist an alias as [server] default_model, which is what the next launch serves."""
        global DEFAULT_MODEL_ALIAS
        if persist_default_model is None:
            self.say_system("model_config.py is missing, so gpt-oss.toml cannot be rewritten here.")
            return
        target = (alias or self.model_label() or "").strip()
        try:
            chosen = persist_default_model(target)
        except (ValueError, OSError) as error:
            self.say_system(f"Could not change the default: {error}")
            return
        DEFAULT_MODEL_ALIAS = chosen
        self.say_system(
            f"Default model is now **{chosen}** ({tier_for(chosen)}).\n\n"
            "start.bat and the next launch serve it; `/models` marks it with a *default* note."
        )

    def action_use_model(self, alias: str) -> None:
        """Select one alias. llama-server serves what it was launched with, so name the gap."""
        if alias not in MODEL_REGISTRY:
            self.notify(f"Unknown alias: {alias}", severity="error")
            return
        self.current_provider = Provider.LLAMA_SERVER
        self.update_client(alias)
        served = self.served_model()
        if served and served != alias:
            self.say_system(f"Chat pinned to **{alias}** ({tier_for(alias)}), but llama-server is serving **{served}**.\n\nRestart it with `python task-engine.py launch --model {alias} --keep-alive`.")
        elif not served:
            self.say_system(f"Chat pinned to **{alias}** ({tier_for(alias)}), but nothing is answering on {LLAMA_ENDPOINT}.\n\nStart it with `python task-engine.py launch --model {alias} --keep-alive`.")

    def action_models(self):
        self.say_system("Local models\n\n" + self.list_models())

    def action_clear(self):
        self.messages = self.messages[:1]
        v = self.query_one("#chat-view", VerticalScroll); v.remove_children(); v.mount(Response("Cleared."))

    # -- sessions: resume, rewind, list ------------------------------------------------------------
    def remember(self, role: str, content: str) -> None:
        """Append one message to the session file. Logging must never break the conversation."""
        if session_log is None or not self.session_id:
            return
        session_log.append(self.session_id, role, content, model=self.model_name)
        self.refresh_history()

    def render_transcript(self) -> None:
        """Redraw the chat view from self.messages, which is the truth after a rewind or resume."""
        view = self.query_one("#chat-view", VerticalScroll)
        view.remove_children()
        for message in self.messages[1:]:
            role = message.get("role")
            if role == "user":
                view.mount(Prompt(str(message.get("content") or "")))
            elif role == "assistant":
                view.mount(Response(str(message.get("content") or "")))
        view.scroll_end(animate=False)

    def refresh_history(self) -> None:
        """Render the saved session index in the sidebar, not in chat."""
        try:
            body = self.query_one("#history-body", Static)
        except Exception:
            return
        if session_log is None:
            body.update("Session history unavailable")
            return
        try:
            rows = session_log.sessions(limit=12)
            if not rows:
                body.update("No saved sessions yet")
                return
            lines = []
            for index, row in enumerate(rows, 1):
                active = "●" if row["id"] == self.session_id else " "
                date = str(row.get("started", ""))[:16].replace("T", " ")
                preview = str(row.get("preview") or "(empty session)").replace("\n", " ")
                lines.append(f"{active} {index}. {date} · {row.get('turns', 0)} turns")
                lines.append(f"   {preview[:42]}")
            body.update("\n".join(lines))
        except Exception as exc:
            body.update(f"History unavailable: {type(exc).__name__}")

    def action_sessions(self) -> None:
        self.refresh_history()
        self.query_one("#history-body", Static).scroll_visible()

    def _session_row(self, which: str) -> dict | None:
        rows = session_log.sessions(limit=50) if session_log else []
        if not rows:
            return None
        which = (which or "").strip()
        if not which:
            return rows[0]
        if which.isdigit():
            index = int(which) - 1
            return rows[index] if 0 <= index < len(rows) else None
        for row in rows:
            if row["id"] == which or row["id"].startswith(which):
                return row
        return None

    def action_resume(self, which: str = "") -> None:
        """Load a past session back into the conversation. Without an argument, the most recent one."""
        if session_log is None:
            self.say_system("Session logging is unavailable in this environment.")
            return
        row = self._session_row(which)
        if not row:
            self.say_system(f"No session matches `{which}`. `/sessions` lists them.")
            return
        records = session_log.load(row["id"])
        if not records:
            self.say_system(f"`{row['id']}` has no messages on disk.")
            return
        self.session_id = row["id"]
        self.messages = [self.messages[0]] + [
            {"role": record["role"], "content": record["content"]} for record in records
        ]
        self.render_transcript()
        self.refresh_history()
        self.say_system(
            f"Resumed `{row['id']}` — {len(records)} message(s), {row['turns']} turn(s).\n\n"
            "Continuing here appends to the same file; `/rewind` trims it, `/new` starts a different one."
        )

    def action_rewind(self, count: str = "") -> None:
        """Drop the last `count` exchanges (default 1) and persist the shortened transcript."""
        try:
            exchanges = max(1, int(str(count or "1").strip()))
        except ValueError:
            exchanges = 1
        users = [index for index, message in enumerate(self.messages) if message.get("role") == "user"]
        if not users:
            self.say_system("Nothing to rewind — no user turn in this session yet.")
            return
        cut = users[-min(exchanges, len(users))]
        dropped = len(self.messages) - cut
        self.messages = self.messages[:cut]
        if session_log is not None and self.session_id:
            session_log.rewrite(self.session_id, self.messages[1:], model=self.model_name)
        self.render_transcript()
        last = next((m["content"] for m in reversed(self.messages) if m.get("role") == "user"), "")
        tail = f"\n\nThe conversation now ends at: “{str(last)[:120]}”" if last else ""
        self.say_system(f"Rewound {dropped} message(s) ({exchanges} exchange(s)).{tail}")

    def action_new_session(self) -> None:
        if session_log is not None:
            self.session_id = session_log.new_session()
        self.messages = self.messages[:1]
        self.query_one("#chat-view", VerticalScroll).remove_children()
        self.update_workspace_bar()
        self.refresh_history()
        self.say_system(f"New session `{self.session_id}`. `/sessions` lists the old ones; `/resume` loads one.")

    # -- workspace: which folder, and what the model may do with it -----------------------------------
    def system_prompt(self) -> str:
        """The model's brief: where it is, what it may do, and which tools it actually has.

        A model cannot call what it cannot name, so the tool list is spelled out with the phrasings
        that map to each one.
        """
        tools = [
            "list_dir(path) and read_file(path) to look around",
            "git_command(command, arguments) for status/diff/log/show/branch/ls-files/grep",
            "run_command(program, args) for the allowlisted git/python/node",
            "search_history(query) for what was said in earlier sessions",
        ]
        if sandbox.allow_write:
            tools.append("write_file(path, content) and patch_file(path, find, replace) to change files")
        if functions is not None and functions.get("gml_validate") is not None:
            tools.append("gml_validate(path) and gml_assemble(graph_id) to check the GML tensor extension")
        permission = (
            "read-write: writes and patches are allowed here"
            if sandbox.allow_write
            else "read-only: no writes until the human grants it with /allow"
        )
        return (
            "You are the coding assistant inside KNUMATIC, a local terminal. Act with tools instead of "
            "guessing: when a question is about the workspace, call one rather than describing what "
            "you would do.\n"
            f"Workspace: {sandbox.root} — {permission}.\n"
            "Tools: " + "; ".join(tools) + ".\n"
            "git here is read-only (status, diff, log, show, branch, ls-files, grep, describe); there is "
            "no shell and no network. Paths are workspace-relative. If a tool refuses, report the "
            "refusal and why - never claim work you did not do."
            + self.mode_line()
        )

    def mode_line(self) -> str:
        """The daemon mode as a sentence the model can obey, not five bare numbers."""
        if daemon is None or not getattr(self, "mode", ""):
            return ""
        info = daemon.modes().get(self.mode)
        return f"\n{info.prompt()}" if info else ""

    def refresh_system_prompt(self) -> None:
        """Keep the brief in step with the workspace and the grant, for the running conversation."""
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = self.system_prompt()

    def update_workspace_bar(self) -> None:
        try:
            bar = self.query_one("#workspace-bar", WorkspaceBar)
        except Exception:
            return
        bar.show(sandbox.root, sandbox.mode, self.session_id)

    def action_pick_workspace(self) -> None:
        """Open the folder chooser; the chosen path comes back through action_apply_workspace."""
        self.push_screen(WorkspacePicker(sandbox.root), self.action_apply_workspace)

    def action_apply_workspace(self, path: Path | None) -> None:
        if path is None:
            self.say_system("Workspace unchanged.")
            return
        self.action_set_workspace(str(path))

    def action_set_workspace(self, target: str) -> None:
        """Point the model at a folder. Picking a workspace always starts read-only."""
        raw = (target or "").strip().strip('"')
        if not raw:
            self.say_system("Usage: `/workspace <folder>` — the folder the model may read.")
            return
        resolved = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
        if not resolved.is_dir():
            self.say_system(f"`{raw}` is not a folder.")
            return
        was_writable = sandbox.allow_write
        sandbox.set_root(resolved, allow_write=False)
        self.update_workspace_bar()
        self.refresh_system_prompt()
        note = " Write permission was dropped with the old folder." if was_writable else ""
        self.say_system(
            f"Workspace is now `{resolved}` — read-only.{note}\n\n"
            "`/allow` lets the model write and patch here; `/allow off` takes it back."
        )

    def action_allow(self, argument: str = "") -> None:
        """The human's switch for write and patch access on the current workspace."""
        word = (argument or "").strip().lower()
        allow = word not in {"off", "no", "read", "readonly", "read-only", "false"}
        sandbox.allow_write = allow
        self.update_workspace_bar()
        self.refresh_system_prompt()
        if allow:
            self.say_system(
                f"**{sandbox.root}** is read-write for this session: the model can `write_file` and "
                "`patch_file` inside it.\n\n`/allow off` revokes that; choosing another folder resets it."
            )
        else:
            self.say_system(f"**{sandbox.root}** is read-only again: reads, searches and allowlisted commands only.")

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with VerticalScroll(id="chat-view"):
                # The logo is part of the first chat entry, not a fixed header.
                # It scrolls away naturally as the conversation grows.
                logo_path = APP_ROOT / "logo.png"
                with Horizontal(id="welcome-logo-row"):
                    if TerminalImage is not None and logo_path.is_file():
                        yield TerminalImage(str(logo_path), id="welcome-logo")
                    else:
                        yield LogoArt(id="welcome-logo")
                yield Response("Agent active. Type 'list_dir .' to inspect files, or 'search web for X'.\n\nTask commands: `/task fix header size`, add task …, done …, start …, block …, priority high …, task list.\n\nGit, answered locally from AIML (no model needed): `what changed`, `show the diff`, `recent commits`, `which branch`, `tracked files`, `last commit`, `what is the time`, `convert 25 celsius to fahrenheit`.\n\nModels: `/models` lists them fastest → deepest, `/model <alias>` picks one for this session, `/default <alias>` makes it what start.bat serves next time, Ctrl+P opens the palette.\n\nAdvisors: `/keys` shows where each API key comes from, `/advisor openai|deepseek|anthropic` switches, `/local` comes back.\n\nWorkspace: `/workspace` (or Ctrl+P) picks the folder the model may read, `/allow` grants write and patch, `/allow off` revokes it — choosing another folder resets the grant.")
            with Vertical(id="task-panel"):
                with Vertical(id="task-section"):
                    yield Static("TASKS", id="task-title")
                    yield Static("", id="task-body")
                with Vertical(id="history-section"):
                    yield Static("HISTORY", id="history-title")
                    yield Static("", id="history-body")
                    yield Static("/resume N  /new  /rewind N", id="history-help")
                with Vertical(id="runtime-section"):
                    yield Static("RUNTIME (read-only)", id="runtime-title")
                    yield Static("", id="green-screen")
                    yield Static("polled · digests compared · nothing woken", id="runtime-help")
        yield Static("", id="completion-hint")
        yield Input(placeholder="Type your message here... (Ctrl+Space to complete)")
        yield WorkspaceBar(id="workspace-bar")
        yield Footer()

    def on_resize(self, event) -> None:
        """Record the viewport dimensions reported by Textual for resize diagnosis.

        Textual normally relayouts automatically; avoid forcing a second refresh
        from inside its resize event, which can interfere with the redraw cycle.
        """
        try:
            from datetime import datetime as _datetime
            with (APP_ROOT / "resize-debug.log").open("a", encoding="utf-8") as log:
                log.write(
                    f"{_datetime.now().isoformat(timespec='seconds')} "
                    f"event={event.size} app={self.size} screen={self.screen.size}\n"
                )
        except (OSError, AttributeError):
            pass

    def on_mount(self) -> None:
        self.update_workspace_bar()
        self.refresh_history()
        if not self.bus:
            return
        self.render_tasks(self.bus.snapshot())
        # The bus runs a poll thread; Textual widgets may only be touched on the app thread.
        self.bus.subscribe(lambda document: self.call_from_thread(self.render_tasks, document))

    def on_unmount(self) -> None:
        if self.bus:
            self.bus.stop()

    def render_tasks(self, document: dict) -> None:
        try:
            body = self.query_one("#task-body", Static)
        except Exception:
            return
        body.update("\n".join(render_panel(document)))

    @on(Input.Submitted)
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text: return
        event.input.value = ""
        self.request_id = uuid.uuid4().hex[:12]
        v = self.query_one("#chat-view", VerticalScroll)
        v.mount(Prompt(text))
        v.scroll_end(animate=False)

        # 0. Slash commands: /models, /model <alias>, /clear, /switch_llama …
        if text.startswith("/"):
            self.handle_command(text)
            return

        # 0.5. A pending deepening offer: agreeing sends the *original* question to the model.
        if self.pending_deep and AFFIRMATIVE.match(text.strip()):
            question = self.pending_deep
            self.pending_deep = None
            v.mount(ToolLog(f"Deepening: asking the model about {question!r}"))
            self.stream_llm_response(question)
            return
        self.pending_deep = None  # anything else cancels the offer

        # 1. Task-list commands, resolved through the AIML bank by the bus.
        # Both /task and \task use the same task-list mutation path.
        task_match = re.fullmatch(r"\\task(?:\s+(.*))?", text, flags=re.IGNORECASE | re.DOTALL)
        if task_match:
            self.add_task(task_match.group(1) or "")
            return
        if self.bus:
            outcome = self.bus.apply(text)
            if outcome["ok"] or outcome.get("intent"):
                v.mount(Response(f"**[Tasks]**\n\n{outcome['reply']}"))
                return

        # 2. Fast path: only what can be answered for real. A fabricated "Result for ..." is worse
        # than no answer, because it looks like a tool ran.
        outcome = fast_path_outcome(text)
        if outcome:
            if outcome["action"] == "math":
                v.mount(Response(f"**[Local math]**\n\n`{outcome['argument']}` = "
                                 f"**{outcome['result']}**"))
                return
            v.mount(ToolLog(outcome["note"]))
            self.stream_llm_response(text)
            return

        # 3. AIML, including its tool bridge: a template that says TOOL git status runs it here and
        # returns the output instead of paying for a model round trip.
        started = time.monotonic()
        local = self.local_answer(text)
        elapsed = int(round((time.monotonic() - started) * 1000))
        if local:
            kind_of, _ = local
            self.record_turn(text, kind=kind_of, latency_ms=elapsed, inference="local",
                             observed_execution=kind_of in {"tool", "gitop", "compose", "memory",
                                                           "memquery"},
                             execution_kind=("host_operation" if kind_of in {"tool", "gitop", "compose",
                                                                             "memory", "memquery"}
                                             else None))
        else:
            self.record_turn(text, kind="deferred", latency_ms=elapsed, inference="model")
        if local:
            kind, body = local
            headings = {
                "tool": "Local tool (AIML → sandbox)",
                "aiml": "Local AIML",
                "error": "Local tool refused",
                "refused": "Local refusal (not authorized)",
                "memory": "Local memory (JSONL history)",
                "memquery": "Local memory (GML projection)",
                "plan": "Local plan (declarations only)",
                "gitop": "Local git (real output, real errors)",
            }
            heading = headings.get(kind, "Local")
            if kind == "tool":
                v.mount(Response(f"**[{heading}]**\n\n```\n{body}\n```"))
            else:
                v.mount(Response(f"**[{heading}]**\n\n{body}"))
            return

        # 4. LLM with Tools - and say why the turn got here, so routing is visible rather than silent.
        v.mount(ToolLog(self.routing_note()))
        self.stream_llm_response(text)

    def routing_note(self) -> str:
        """One line explaining why a turn is going to the model instead of being answered locally."""
        turn = self.last_turn
        if turn is None:
            return "No local match → delegating to the model."
        trace = dict(turn.phases)
        why = (trace.get("Ch'en") or trace.get("Yax") or "").strip()
        if not why or why == "nothing to admit":
            why = "the AIML banks had no reply for that"
        return f"No local answer → delegating to the model ({why})."

    @work(exclusive=True)
    async def stream_llm_response(self, user_text: str) -> None:
        v = self.query_one("#chat-view", VerticalScroll)
        self.messages.append({"role": "user", "content": user_text})
        self.remember("user", user_text)
        resp = Response("")
        v.mount(resp)
        v.scroll_end(animate=False)

        # Register Sandbox Tools for the LLM. search_history is always available: looking back at
        # earlier sessions is read-only.
        tools = [
            pydantic_function_tool(ListDirArgs),
            pydantic_function_tool(ReadFileArgs),
            pydantic_function_tool(RunCommandArgs),
            pydantic_function_tool(GitArgs),
            pydantic_function_tool(HistoryArgs),
        ]
        if sandbox.allow_write:
            # Only offered when the human has granted writes for this workspace, so the model is not
            # shown a tool that would only ever refuse.
            tools.append(pydantic_function_tool(WriteFileArgs))
            tools.append(pydantic_function_tool(PatchFileArgs))
            tools.append(pydantic_function_tool(CloneArgs))
        if functions is not None and functions.get("gml_validate") is not None:
            # The K'UHUL base's own extension contract: read-only validation and a plan-only assembly.
            tools.append(pydantic_function_tool(GmlValidateArgs))
            tools.append(pydantic_function_tool(GmlAssembleArgs))

        # One lease for this turn: StreamingCall owns it, so nothing else acquires one. The lease spans the
        # iteration below, which is the stream Textual actually consumes.
        turn = None
        if inference_session is not None and self.waker is not None and self.lifecycle is not None:
            backend = model_lifecycle.backend_for_alias(self.lifecycle.declaration, self.model_name)
            if backend is None:
                # Not silent: an unmanaged turn is recorded, even though the stream still proceeds.
                self.unmanaged_streams += 1
                self.last_unmanaged = model_lifecycle.diagnose_backend(
                    self.lifecycle.declaration, self.model_name)
            if backend is not None:
                turn = inference_session.StreamingCall(
                    self.waker, backend, self.messages, None,
                    request_id=self.request_id, record=False)
                try:
                    turn.begin()
                except Exception:
                    turn = None          # a model the lifecycle cannot wake still streams as before

        try:
            with self.client.chat.completions.stream(
                model=self.model_name,
                messages=self.messages,
                tools=tools,
            ) as stream:
                full = ""
                for event in stream:
                    if event.type == "content.delta":
                        if turn is not None:
                            turn.note_chunk(event.delta)
                        full += event.delta
                        resp.update(full)
                        v.scroll_end(animate=False)
                
                final = stream.get_final_completion()
                message = final.choices[0].message
                self.messages.append(message.model_dump(exclude_none=True))
                
                if message.tool_calls:
                    for tc in message.tool_calls:
                        v.mount(ToolLog(f"Tool Call: **{tc.function.name}**"))
                        try:
                            import json
                            args = json.loads(tc.function.arguments)
                            result = execute_tool(tc.function.name, args)
                            self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                        except Exception as e:
                            self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"Error: {e}"})

                    # Get the LLM to summarize the tool output
                    await self.follow_up_llm_response()
                elif full.strip():
                    # The answer arrived inline: this is the turn to remember for /resume and /rewind.
                    self.remember("assistant", full)

        except Exception as e:
            resp.update(f"**LLM Error:** {e}")
            if turn is not None:
                turn.error = f"{type(e).__name__}: {e}"[:200]
        finally:
            if turn is not None:
                # Evidence, not success: a failed or interrupted stream still records its observation.
                self.last_stream = turn.measurements
                self.last_stream_error = turn.error
                try:
                    turn.end(error=turn.error)
                    self.last_stream = turn.measurements
                    self.last_record = evidence_record.append(evidence_record.build(
                        input_text=user_text, request_id=self.request_id, inference="model",
                        model_id=self.model_name, latency_ms=turn.total_ms,
                        schema_validation=("error" if turn.error else "streamed"),
                        operators=[]))
                except Exception as problem:      # losing an observation is a defect, not a failure
                    self.last_stream_error = f"{type(problem).__name__}: {problem}"
            v.scroll_end(animate=False)

    async def follow_up_llm_response(self):
        v = self.query_one("#chat-view", VerticalScroll)
        resp = Response("")
        v.mount(resp)
        try:
            with self.client.chat.completions.stream(
                model=self.model_name,
                messages=self.messages,
            ) as stream:
                full = ""
                for event in stream:
                    if event.type == "content.delta":
                        full += event.delta
                        resp.update(full)
                        v.scroll_end(animate=False)
                final = stream.get_final_completion()
                self.messages.append(final.choices[0].message.model_dump(exclude_none=True))
                answer = final.choices[0].message.content or ""
                self.maybe_reference(answer, last_user=user_text, response=resp)
                self.remember("assistant", answer)
                # One shared log for every local client: the dumper compiles these pairs into AIML.
                last_user = next((m["content"] for m in reversed(self.messages) if m.get("role") == "user"), "")
                log_interaction(
                    app="chat_app",
                    user=last_user,
                    assistant=final.choices[0].message.content or "",
                    model=self.model_name,
                    status="ANSWERED",
                )
        except Exception as e:
            resp.update(f"**LLM Error:** {e}")

def _serve_cli():
    """`python chat_app.py --serve 8756` runs the TUI and the loopback endpoint together."""
    import sys as _sys

    argv = list(_sys.argv)
    port = micronaut_server.DEFAULT_PORT if micronaut_server else 8756
    if "--serve" in argv:
        index = argv.index("--serve")
        argv.pop(index)
        if index < len(argv) and argv[index].isdigit():
            port = int(argv.pop(index))
        _sys.argv = argv
    app = ChatApp()
    if micronaut_server is not None:
        engine = micronaut_server.Engine(app=app)
        app.server = micronaut_server.serve(port, block=False, engine=engine)
        threading.Thread(target=app.server.serve_forever, daemon=True).start()
        host, bound = app.server.server_address[:2]
        print(f"{micronaut_server.uri()} -> http://{host}:{bound}/v1/chat", flush=True)
    app.run()


if __name__ == "__main__":
    _serve_cli()