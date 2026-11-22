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
import math
import subprocess
import shutil
from pathlib import Path
from enum import Enum
from typing import Callable
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Input, Footer, Markdown, Static
from openai import OpenAI, pydantic_function_tool
from pydantic import BaseModel, Field
import aiml
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

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
    def __init__(self, root: Path):
        self.root = root.resolve()

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

# Initialize Sandbox to the current directory
sandbox = Sandbox(Path("."))

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

def execute_tool(name: str, args: dict) -> str:
    try:
        if name == "list_dir":
            return sandbox.list_dir(args.get("path", "."))
        elif name == "read_file":
            return sandbox.read_file(args["path"])
        elif name == "run_command":
            return sandbox.run_command(args["program"], args["args"])
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
    """Read the same patches/gpt-oss.toml the terminal uses.

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


class Provider(Enum):
    OLLAMA = "ollama"
    LLAMA_SERVER = "llama-server"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"

PROVIDER_CONFIGS = {
    Provider.OLLAMA: {"base_url": "http://localhost:11434/v1", "api_key": "ollama", "default_model": "llama3"},
    # The local llama-server the terminal launches; it serves one model, so "auto" is resolved from
    # /v1/models rather than assumed.
    Provider.LLAMA_SERVER: {"base_url": LLAMA_ENDPOINT + "/v1", "api_key": "local", "default_model": "auto"},
    Provider.OPENAI: {"base_url": None, "api_key": os.environ.get("OPENAI_API_KEY"), "default_model": "gpt-4o"},
    Provider.DEEPSEEK: {"base_url": "https://api.deepseek.com/v1", "api_key": os.environ.get("DEEPSEEK_API_KEY"), "default_model": "deepseek-chat"},
}

class Prompt(Markdown): BORDER_TITLE = "You"
class Response(Markdown): BORDER_TITLE = "Assistant"
class ToolLog(Markdown): BORDER_TITLE = "System Log"

class ChatApp(App):
    CSS = """
    Screen { layout: vertical; }
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
        self.current_provider = Provider.OLLAMA
        self.client = None
        self.model_name = ""
        self.messages = [{"role": "system", "content": "You are a helpful coding assistant. Use tools to inspect the repo."}]
        self.bus = TaskListBus().start() if TaskListBus else None
        self.update_client()
        self.router = self.get_semantic_router()

    def update_client(self):
        config = PROVIDER_CONFIGS[self.current_provider]
        self.model_name = config["default_model"]
        if self.current_provider is Provider.LLAMA_SERVER and self.model_name == "auto":
            self.model_name = self.served_model() or DEFAULT_MODEL_ALIAS
        if config["base_url"]:
            self.client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
        else:
            self.client = OpenAI(api_key=config["api_key"])
        self.notify(f"Switched to {self.current_provider.value}")

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
            return "No models registered in patches/gpt-oss.toml"
        served = self.served_model()
        lines = [f"Endpoint: {LLAMA_ENDPOINT}", f"Serving:  {served or '(nothing loaded)'}", ""]
        for alias in sorted(MODEL_REGISTRY):
            path = model_path_for(alias)
            state = "ok" if path.is_file() else "MISSING"
            gb = f"{path.stat().st_size / (1024 ** 3):.2f} GB" if path.is_file() else "? GB"
            mark = "*" if alias == DEFAULT_MODEL_ALIAS else " "
            lines.append(f"{mark} {alias:<16} {gb:>8}  {state}")
        lines.append("")
        lines.append("* default  ·  switch with switch_llama, then launch that model in the terminal")
        return "\n".join(lines)

    def get_semantic_router(self):
        kernel = aiml.Kernel()
        alice_dir = Path("aiml-en-us-foundation-alice")
        if alice_dir.exists():
            startup = alice_dir / "startup.xml"
            if startup.exists(): kernel.learn(str(startup))
        
        # Fallback override
        kernel.learn("_override.aiml") if Path("_override.aiml").exists() else None
        kernel.setBotPredicate("name", "KNUMATIC")
        return kernel

    def get_commands(self):
        return {
            "switch_ollama": ("Switch to Ollama", lambda: self.action_switch(Provider.OLLAMA)),
            "switch_openai": ("Switch to OpenAI", lambda: self.action_switch(Provider.OPENAI)),
            "switch_deepseek": ("Switch to DeepSeek", lambda: self.action_switch(Provider.DEEPSEEK)),
            "switch_llama": ("Switch to local llama-server", lambda: self.action_switch(Provider.LLAMA_SERVER)),
            "models": ("List local models", self.action_models),
            "clear": ("Clear Chat", self.action_clear),
        }

    def action_switch(self, p): self.current_provider = p; self.update_client()

    def action_models(self):
        view = self.query_one("#chat-view", VerticalScroll)
        view.mount(ToolLog("Local models\n\n" + self.list_models()))
        view.scroll_end(animate=False)
    def action_clear(self):
        self.messages = self.messages[:1]
        v = self.query_one("#chat-view", VerticalScroll); v.clear(); v.mount(Response("Cleared."))

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with VerticalScroll(id="chat-view"):
                yield Response("Agent active. Type 'list_dir .' to inspect files, or 'search web for X'.\n\nTask commands: add task …, done …, start …, block …, priority high …, task list.")
            with Vertical(id="task-panel"):
                yield Static("TASKS", id="task-title")
                yield Static("", id="task-body")
        yield Input(placeholder="Type your message here...")
        yield Footer()

    def on_mount(self) -> None:
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

        # 0. Task-list commands, resolved through the AIML bank by the bus.
        if self.bus:
            outcome = self.bus.apply(text)
            if outcome["ok"] or outcome.get("intent"):
                v.mount(Response(f"**[Tasks]**\n\n{outcome['reply']}"))
                return

        # 1. Regex Fast-Path
        intent, arg = check_regex_fast_path(text)
        if intent:
            v.mount(ToolLog(f"Fast-Path Triggered: {intent}"))
            if intent == "search_web": res = f"🌐 Result for {arg}"
            else: res = f"🧮 Result for {arg}"
            v.mount(Response(f"**[Local Execution]**\n\n{res}"))
            return

        # 2. AIML
        aiml_res = self.router.respond(text.upper())
        if aiml_res and "__LLM_FALLBACK__" not in aiml_res:
            v.mount(Response(f"**[Local AIML]**\n\n{aiml_res}"))
            return

        # 3. LLM with Tools
        v.mount(ToolLog("Delegating to LLM with Sandbox Tools..."))
        self.stream_llm_response(text)

    @work(exclusive=True)
    async def stream_llm_response(self, user_text: str) -> None:
        v = self.query_one("#chat-view", VerticalScroll)
        self.messages.append({"role": "user", "content": user_text})
        resp = Response("")
        v.mount(resp)
        v.scroll_end(animate=False)

        # Register Sandbox Tools for the LLM
        tools = [
            pydantic_function_tool(ListDirArgs),
            pydantic_function_tool(ReadFileArgs),
            pydantic_function_tool(RunCommandArgs),
        ]

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