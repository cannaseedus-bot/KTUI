# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "textual>=0.58.0",
#     "openai>=1.40.0",
#     "pydantic>=2.0",
#     "python-aiml",
#     "requests",
#     "beautifulsoup4",
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
try:  # the header mark: an allowlisted subset of SVG, rasterised to half blocks
    import svg_logo
except ImportError:  # pragma: no cover
    svg_logo = None
import math
import subprocess
import shutil
import requests
import webbrowser
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
        
        argv = [program] + args
        try:
            res = subprocess.run(argv, cwd=str(self.root), capture_output=True, text=True, timeout=10, shell=False)
            out = res.stdout.strip() or res.stderr.strip() or "(no output)"
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
    program: str = Field(..., description="git, python, node")
    args: list[str] = Field(..., description="List of string arguments")
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


def format_history(rows: list[dict]) -> str:
    """The model's view of the transcript: when, which session, who, and a bounded excerpt."""
    if not rows:
        return "no earlier messages recorded yet"
    lines = []
    for row in rows:
        when = str(row.get("at") or "")[:16].replace("T", " ")
        lines.append(f"[{when}] {str(row.get('session') or '')[:6]} {row.get('role')}: {str(row.get('content') or '')[:400]}")
    return "\n".join(lines)


def execute_tool(name: str, args: dict) -> str:
    try:
        if name == "list_dir":
            return sandbox.list_dir(args.get("path", "."))
        elif name == "read_file":
            return sandbox.read_file(args["path"])
        elif name == "run_command":
            return sandbox.run_command(args["program"], args["args"])
        elif name == "search_history":
            if session_log is None:
                return "session logging is unavailable"
            rows = session_log.search(str(args.get("query") or ""), limit=int(args.get("limit") or 10))
            return format_history(rows)
        elif name == "write_file":
            return sandbox.write_file(args["path"], args.get("content", ""))
        elif name == "patch_file":
            return sandbox.patch_file(args["path"], args["find"], args.get("replace", ""), bool(args.get("replace_all")))
    except SandboxError as e:
        return f"🚫 [Sandbox Refused]: {e}"
    except Exception as e:
        return f"❌ [Error]: {e}"
    return "Unknown tool"

# Regex Fast-Path (for Instant local execution)
def check_regex_fast_path(text: str):
    text_lower = text.lower()
    # Web search
    search_match = re.search(r"(?:search(?: the)? web for|look up) (.*)", text_lower)
    if search_match: return "search_web", search_match.group(1).strip()
    # Math
    math_match = re.search(r"(?:calculate|math) (.*)", text_lower)
    if math_match: return "compute_math", math_match.group(1).strip()
    return None, None

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
    """The header mark, drawn from logo.svg and breathed by a timer.

    Textual has no SVG renderer, so svg_logo.py rasterises an allowlisted subset to half blocks and
    this widget re-renders it every few frames: the shape tagged id="pulse" brightens and dims. The
    SVG stays a static, script-free file - the animation lives here, not in the artwork.
    """

    DEFAULT_CSS = """
    LogoArt { width: 24; height: 12; content-align: center middle; }
    """

    def __init__(self, *, cols: int = 22, rows: int = 22, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self.cols = cols
        self.rows = rows
        self.phase = 0.0
        self.logo = None
        self.problem = ""

    def on_mount(self) -> None:
        if svg_logo is None:
            self.problem = "logo module missing"
        else:
            try:
                self.logo = svg_logo.load_default()
            except Exception as error:  # unsafe, missing or malformed: say so and keep running
                self.problem = f"logo: {error}"
        self.draw()
        self.set_interval(0.16, self.tick)

    def tick(self) -> None:
        self.phase = (self.phase + 0.16) % 1.0
        self.draw()

    def pulse(self) -> float:
        """A smooth 0..0.85 breath, so the marker does not flicker."""
        return (math.sin(self.phase * 2 * math.pi) + 1) / 2 * 0.85

    def draw(self) -> None:
        if self.problem:
            self.update(self.problem)
            return
        try:
            self.update(self.logo.render(self.cols, self.rows, brighten={"pulse": self.pulse()}))
        except Exception as error:
            self.problem = f"logo: {error}"
            self.update(self.problem)


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
        text.append(f"{shown}\n")
        text.append("model      ", style="bold")
        text.append(f"{mode}", style="green" if mode == "read-write" else "yellow")
        text.append("   `/workspace` picks a folder, `/allow` grants write+patch\n", style="dim")
        text.append("session    ", style="bold")
        text.append(session or "(not recording)", style="dim")
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


class ChatApp(App):
    # The palette is the model switcher: system commands (screen, quit…) plus ChatCommands below.
    COMMANDS = App.COMMANDS | {ChatCommands}
    CSS = """
    Screen { layout: vertical; }
    #banner { height: 12; padding: 0 1; background: $panel; border-bottom: solid $primary 30%; }
    #logo { width: 24; height: 12; content-align: center middle; }
    #workspace-bar { width: 1fr; height: 12; content-align: left middle; }
    #main { height: 1fr; }
    #chat-view { width: 2fr; height: 1fr; padding: 1 2; background: $surface; }
    #task-panel { width: 1fr; border: round $secondary; padding: 0 1; }
    #task-title { content-align: center middle; text-style: bold; height: 1; }
    Prompt { border: round $primary; margin: 1 0; padding: 1; background: $primary 10%; }
    Response { border: round $success; margin: 1 0; padding: 1; background: $success 10%; }
    ToolLog { border: round $warning; margin: 1 0; padding: 1; background: $warning 10%; color: $text-muted; }
    Input { dock: bottom; margin: 1; }
    """
    AUTO_FOCUS = "Input"

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
        self.messages = [{"role": "system", "content": "You are a helpful coding assistant. Use tools to inspect the repo."}]
        self.bus = TaskListBus().start() if TaskListBus else None
        self.update_client()
        self.router = self.get_semantic_router()

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
        kernel = aiml.Kernel()
        alice_dir = APP_ROOT / "aiml-en-us-foundation-alice"
        if alice_dir.exists():
            startup = alice_dir / "startup.xml"
            if startup.exists(): kernel.learn(str(startup))

        # Fallback override, also anchored to the repository root
        override = APP_ROOT / "_override.aiml"
        kernel.learn(str(override)) if override.exists() else None
        kernel.setBotPredicate("name", "KNUMATIC")
        return kernel

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
        commands["clear"] = ("Chat: clear", self.action_clear, "Drop the conversation, keep the system prompt")
        return commands

    def handle_command(self, text: str) -> None:
        """`/models`, `/model <alias>`, `/advisor <name>`, or any key from get_commands()."""
        name, _, argument = text[1:].partition(" ")
        name, argument = name.strip().lower(), argument.strip()
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
        if name in {"workspace", "cwd"}:
            if argument:
                self.action_set_workspace(argument)
            else:
                self.action_pick_workspace()
            return
        if name in {"allow", "writes", "edit"}:
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

    def action_sessions(self) -> None:
        if session_log is None:
            self.say_system("Session logging is unavailable in this environment.")
            return
        rows = session_log.sessions(limit=10)
        if not rows:
            self.say_system("No sessions recorded yet — this one starts now.")
            return
        lines = ["Recent sessions, newest first:", ""]
        for index, row in enumerate(rows, start=1):
            when = str(row["started"])[:16].replace("T", " ")
            mark = "*" if row["id"] == self.session_id else " "
            lines.append(f"{mark}{index}. `{row['id']}` · {when} · {row['turns']} turn(s) · {row['preview']}")
        lines.append("")
        lines.append("`/resume <number|id>` loads one, `/rewind [n]` drops the last n exchanges, `/new` starts fresh.")
        lines.append("* marks the session you are in.")
        self.say_system("\n".join(lines))

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
        self.say_system(f"New session `{self.session_id}`. `/sessions` lists the old ones; `/resume` loads one.")

    # -- workspace: which folder, and what the model may do with it -----------------------------------
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
        if allow:
            self.say_system(
                f"**{sandbox.root}** is read-write for this session: the model can `write_file` and "
                "`patch_file` inside it.\n\n`/allow off` revokes that; choosing another folder resets it."
            )
        else:
            self.say_system(f"**{sandbox.root}** is read-only again: reads, searches and allowlisted commands only.")

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="banner"):
            yield LogoArt(id="logo")
            yield WorkspaceBar(id="workspace-bar")
        with Horizontal(id="main"):
            with VerticalScroll(id="chat-view"):
                yield Response("Agent active. Type 'list_dir .' to inspect files, or 'search web for X'.\n\nTask commands: add task …, done …, start …, block …, priority high …, task list.\n\nModels: `/models` lists them fastest → deepest, `/model <alias>` picks one for this session, `/default <alias>` makes it what start.bat serves next time, Ctrl+P opens the palette.\n\nAdvisors: `/keys` shows where each API key comes from, `/advisor openai|deepseek|anthropic` switches, `/local` comes back.\n\nWorkspace: `/workspace` (or Ctrl+P) picks the folder the model may read, `/allow` grants write and patch, `/allow off` revokes it — choosing another folder resets the grant.\n\nHistory: `/sessions` lists past conversations, `/resume [n]` loads one, `/rewind [n]` drops the last exchanges, `/new` starts fresh.")
            with Vertical(id="task-panel"):
                yield Static("TASKS", id="task-title")
                yield Static("", id="task-body")
        yield Input(placeholder="Type your message here...")
        yield Footer()

    def on_mount(self) -> None:
        self.update_workspace_bar()
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
        v = self.query_one("#chat-view", VerticalScroll)
        v.mount(Prompt(text))
        v.scroll_end(animate=False)

        # 0. Slash commands: /models, /model <alias>, /clear, /switch_llama …
        if text.startswith("/"):
            self.handle_command(text)
            return

        # 1. Task-list commands, resolved through the AIML bank by the bus.
        if self.bus:
            outcome = self.bus.apply(text)
            if outcome["ok"] or outcome.get("intent"):
                v.mount(Response(f"**[Tasks]**\n\n{outcome['reply']}"))
                return

        # 2. Regex Fast-Path
        intent, arg = check_regex_fast_path(text)
        if intent:
            v.mount(ToolLog(f"Fast-Path Triggered: {intent}"))
            if intent == "search_web": res = f"🌐 Result for {arg}"
            else: res = f"🧮 Result for {arg}"
            v.mount(Response(f"**[Local Execution]**\n\n{res}"))
            return

        # 3. AIML
        aiml_res = self.router.respond(text.upper())
        if aiml_res and "__LLM_FALLBACK__" not in aiml_res:
            v.mount(Response(f"**[Local AIML]**\n\n{aiml_res}"))
            return

        # 4. LLM with Tools
        v.mount(ToolLog("Delegating to LLM with Sandbox Tools..."))
        self.stream_llm_response(text)

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
            pydantic_function_tool(HistoryArgs),
        ]
        if sandbox.allow_write:
            # Only offered when the human has granted writes for this workspace, so the model is not
            # shown a tool that would only ever refuse.
            tools.append(pydantic_function_tool(WriteFileArgs))
            tools.append(pydantic_function_tool(PatchFileArgs))

        try:
            with self.client.chat.completions.stream(
                model=self.model_name,
                messages=self.messages,
                tools=tools,
            ) as stream:
                full = ""
                for event in stream:
                    if event.type == "content.delta":
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
        finally:
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

if __name__ == "__main__":
    app = ChatApp()
    app.run()