"""Task list bus: one JSON file, watched, with AIML/SRAI commands for updating it.

`task-list.json` is the rendered state; this module is the only thing that writes it. Two clients use
it today — the terminal (where the model can maintain the list through a tool) and the chat app (which
renders it in a side panel) — and either can be replaced by anything that speaks the same file plus the
same commands.

The bus is deliberately dependency-free: a poll thread compares a digest of the file and emits a
snapshot when it changes, so an external edit (an editor, a model, another process) shows up in the
panel without a refresh. Local mutations notify immediately rather than waiting for the next poll.

Commands are AIML, not English parsing: patterns with `*`, one-to-one `<srai>` redirects and `<star/>`
substitution, resolved by the same rules the hosted daemon uses (literal-word specificity, bounded
redirects). A template ends in `COMMAND <intent> <args>`, which is data — the resolver returns an
intent and the store decides what it means.

    python patches/task_list.py list
    python patches/task_list.py add "wire the task bus"
    python patches/task_list.py command "done 2"
    python patches/task_list.py watch
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = REPO_ROOT / "task-list.json"
SCHEMA = "knumatic.task-list/1"

STATUSES = ("todo", "doing", "blocked", "done")
PRIORITIES = ("low", "medium", "high")
MAX_TASKS = 200
MAX_TITLE = 160
SRAI_DEPTH = 4

# The command bank. A template is either another pattern (`<srai>`) or the resolved command. Keeping
# the phrases in AIML means a new way of saying "finish this" is a line of data, not a branch in code.
BANK = """
<aiml>
  <category><pattern>ADD TASK *</pattern><template>COMMAND add <star/></template></category>
  <category><pattern>NEW TASK *</pattern><template><srai>ADD TASK <star/></srai></template></category>
  <category><pattern>TASK ADD *</pattern><template><srai>ADD TASK <star/></srai></template></category>
  <category><pattern>REMEMBER TO *</pattern><template><srai>ADD TASK <star/></srai></template></category>
  <category><pattern>COMPLETE TASK *</pattern><template>COMMAND done <star/></template></category>
  <category><pattern>FINISH TASK *</pattern><template><srai>COMPLETE TASK <star/></srai></template></category>
  <category><pattern>DONE TASK *</pattern><template><srai>COMPLETE TASK <star/></srai></template></category>
  <category><pattern>DONE *</pattern><template><srai>COMPLETE TASK <star/></srai></template></category>
  <category><pattern>START TASK *</pattern><template>COMMAND start <star/></template></category>
  <category><pattern>BEGIN TASK *</pattern><template><srai>START TASK <star/></srai></template></category>
  <category><pattern>BEGIN *</pattern><template><srai>START TASK <star/></srai></template></category>
  <category><pattern>BLOCK TASK *</pattern><template>COMMAND block <star/></template></category>
  <category><pattern>UNBLOCK TASK *</pattern><template>COMMAND unblock <star/></template></category>
  <category><pattern>REMOVE TASK *</pattern><template>COMMAND remove <star/></template></category>
  <category><pattern>DELETE TASK *</pattern><template><srai>REMOVE TASK <star/></srai></template></category>
  <category><pattern>DELETE *</pattern><template><srai>REMOVE TASK <star/></srai></template></category>
  <category><pattern>PRIORITY * *</pattern><template>COMMAND priority <star/> <star/></template></category>
  <category><pattern>CLEAR DONE</pattern><template>COMMAND clear_done</template></category>
  <category><pattern>CLEAR TASKS</pattern><template>COMMAND clear_all</template></category>
  <category><pattern>SHOW TASKS</pattern><template>COMMAND list</template></category>
  <category><pattern>TASK LIST</pattern><template><srai>SHOW TASKS</srai></template></category>
  <category><pattern>LIST TASKS</pattern><template><srai>SHOW TASKS</srai></template></category>
  <category><pattern>TASKS</pattern><template><srai>SHOW TASKS</srai></template></category>
</aiml>
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- AIML subset (same rules as base44/shared/aimlSrai.ts, in Python) -------------------------------

def normalize(text: str) -> str:
    value = str(text or "").upper()
    value = re.sub(r"[^A-Z0-9*_\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_bank(source: str) -> list[dict]:
    categories = []
    for block in re.findall(r"<category>(.*?)</category>", source, flags=re.DOTALL):
        pattern_match = re.search(r"<pattern>(.*?)</pattern>", block, flags=re.DOTALL)
        template_match = re.search(r"<template>(.*?)</template>", block, flags=re.DOTALL)
        if not pattern_match or not template_match:
            continue
        pattern = normalize(pattern_match.group(1))
        if not pattern:
            continue
        categories.append({
            "pattern": pattern,
            "template": template_match.group(1).strip(),
            "literal_words": len(re.sub(r"[*_]", " ", pattern).split()),
        })
    return categories


CATEGORIES = parse_bank(BANK)


def tokenize(text: str) -> list[str]:
    """Split into word tokens the same way normalize() does, but keeping the original case."""
    return re.findall(r"[A-Za-z0-9_*]+", str(text or ""))


def _spans(pattern: str, tokens: list[str]):
    """Where each wildcard of `pattern` lands in `tokens`. Returns None when the pattern does not fit."""
    pattern_words = pattern.split()
    captures: list[tuple[int, int]] = []
    index = 0
    for position, pattern_word in enumerate(pattern_words):
        is_last = position == len(pattern_words) - 1
        if pattern_word in {"*", "_"}:
            next_word = pattern_words[position + 1] if not is_last else None
            begin = index
            if next_word is None:
                index = len(tokens)
            else:
                while index < len(tokens) and tokens[index] != next_word:
                    index += 1
            captures.append((begin, index))
            continue
        if index >= len(tokens) or tokens[index] != pattern_word:
            return None
        index += 1
    if index != len(tokens):
        return None
    return captures


def _capture_words(tokens: list[str], spans: list[tuple[int, int]]) -> list[str]:
    return [" ".join(tokens[begin:end]) for begin, end in spans]


def resolve(text: str, depth: int = 0, visited: set[str] | None = None) -> dict | None:
    """Resolve text to {intent, args} through the bank, following bounded `<srai>` redirects.

    Matching happens on upper-cased tokens, but captures come back from the original words, so a title
    the user typed as "Wire the bus" is stored that way and not shouted back at them.
    """
    visited = visited if visited is not None else set()
    raw_tokens = tokenize(text)
    normal_tokens = [token.upper() for token in raw_tokens]
    if not normal_tokens or depth > SRAI_DEPTH:
        return None
    question = " ".join(normal_tokens)
    if question in visited:
        return None
    visited.add(question)

    best = None
    for category in CATEGORIES:
        spans = _spans(category["pattern"], normal_tokens)
        if spans is None:
            continue
        if best is None or category["literal_words"] > best[0]["literal_words"]:
            best = (category, spans)
    if best is None:
        return None

    category, spans = best
    raw_captures = _capture_words(raw_tokens, spans)
    normal_captures = _capture_words(normal_tokens, spans)

    def fill(source: str, captures: list[str]) -> str:
        remaining = list(captures)
        return re.sub(r"<star\s*/>", lambda _match: remaining.pop(0) if remaining else "", source).strip()

    srai = re.search(r"<srai>(.*?)</srai>", category["template"], flags=re.DOTALL)
    if srai:
        return resolve(fill(srai.group(1), raw_captures), depth + 1, visited)

    marker = re.match(r"COMMAND\s+([a-z_]+)\s*(.*)$", fill(category["template"], raw_captures), flags=re.DOTALL)
    if not marker:
        return None
    return {"intent": marker.group(1), "args": marker.group(2).strip(), "pattern": category["pattern"]}


# -- store -------------------------------------------------------------------------------------------

def empty_document() -> dict:
    return {"schema": SCHEMA, "updated_at": now(), "tasks": []}


def load(path: Path = DEFAULT_PATH) -> dict:
    """Read the document. A missing or broken file is an empty list, never a crash."""
    path = Path(path)
    if not path.is_file():
        return empty_document()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_document()
    tasks = []
    for item in raw.get("tasks") or []:
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            continue
        tasks.append({
            "id": str(item.get("id") or uuid.uuid4().hex[:8]),
            "title": str(item["title"]).strip()[:MAX_TITLE],
            "status": item.get("status") if item.get("status") in STATUSES else "todo",
            "priority": item.get("priority") if item.get("priority") in PRIORITIES else "medium",
            "note": str(item.get("note") or "")[:400],
            "created_at": item.get("created_at") or now(),
            "updated_at": item.get("updated_at") or now(),
        })
    return {"schema": SCHEMA, "updated_at": raw.get("updated_at") or now(), "tasks": tasks[:MAX_TASKS]}


def save(document: dict, path: Path = DEFAULT_PATH) -> dict:
    """Write atomically: a reader never sees a half-written list."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema": SCHEMA,
        "updated_at": now(),
        "tasks": list(document.get("tasks") or [])[:MAX_TASKS],
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return document


def _find(tasks: list[dict], selector: str) -> dict | None:
    """Find a task by id, by its 1-based position, or by a distinctive part of its title."""
    needle = str(selector or "").strip().lower()
    if not needle:
        return None
    for task in tasks:
        if task["id"].lower() == needle:
            return task
    if needle.isdigit():
        position = int(needle) - 1
        if 0 <= position < len(tasks):
            return tasks[position]
        return None
    for task in tasks:
        if needle in task["title"].lower():
            return task
    return None


def apply(text: str, path: Path = DEFAULT_PATH) -> dict:
    """Resolve one command and apply it. Returns {ok, intent, reply, document}."""
    path = Path(path)
    resolved = resolve(text)
    if resolved is None:
        return {"ok": False, "intent": None, "reply": "That is not a task command.", "document": load(path)}

    document = load(path)
    tasks = document["tasks"]
    intent, args = resolved["intent"], resolved["args"]
    reply = ""

    if intent == "add":
        title = args.strip()[:MAX_TITLE]
        if not title:
            return {"ok": False, "intent": intent, "reply": "Add what?", "document": document}
        if any(task["title"].lower() == title.lower() for task in tasks):
            return {"ok": False, "intent": intent, "reply": f"Already on the list: {title}", "document": document}
        tasks.append({
            "id": uuid.uuid4().hex[:8], "title": title, "status": "todo", "priority": "medium",
            "note": "", "created_at": now(), "updated_at": now(),
        })
        reply = f"Added: {title}"
    elif intent in {"done", "start", "block", "unblock"}:
        task = _find(tasks, args)
        if not task:
            return {"ok": False, "intent": intent, "reply": f"No task matches {args!r}.", "document": document}
        task["status"] = {"done": "done", "start": "doing", "block": "blocked", "unblock": "todo"}[intent]
        task["updated_at"] = now()
        reply = f"{task['title']} → {task['status']}"
    elif intent == "remove":
        task = _find(tasks, args)
        if not task:
            return {"ok": False, "intent": intent, "reply": f"No task matches {args!r}.", "document": document}
        tasks.remove(task)
        reply = f"Removed: {task['title']}"
    elif intent == "priority":
        parts = args.split()
        level = parts[0].lower() if parts else ""
        selector = " ".join(parts[1:]) if len(parts) > 1 else parts[0] if parts else ""
        if level not in PRIORITIES:
            return {"ok": False, "intent": intent, "reply": f"Priority must be one of {', '.join(PRIORITIES)}.", "document": document}
        task = _find(tasks, selector)
        if not task:
            return {"ok": False, "intent": intent, "reply": f"No task matches {selector!r}.", "document": document}
        task["priority"] = level
        task["updated_at"] = now()
        reply = f"{task['title']} → {level} priority"
    elif intent == "clear_done":
        removed = [task for task in tasks if task["status"] == "done"]
        tasks[:] = [task for task in tasks if task["status"] != "done"]
        reply = f"Cleared {len(removed)} completed task(s)."
    elif intent == "clear_all":
        count = len(tasks)
        tasks.clear()
        reply = f"Cleared the list ({count} task(s))."
    elif intent == "list":
        return {"ok": True, "intent": intent, "reply": render_text(document), "document": document}
    else:  # pragma: no cover - the bank only emits known intents
        return {"ok": False, "intent": intent, "reply": f"Unhandled command {intent!r}.", "document": document}

    saved = save(document, path)
    return {"ok": True, "intent": intent, "reply": reply, "document": saved}


def render_text(document: dict) -> str:
    tasks = document.get("tasks") or []
    if not tasks:
        return "The task list is empty."
    marks = {"todo": "[ ]", "doing": "[>]", "blocked": "[!]", "done": "[x]"}
    lines = []
    for task in tasks:
        lines.append(f"{marks.get(task['status'], '[ ]')} {task['id']}  {task['title']}"
                     + (f"  ({task['priority']})" if task["priority"] != "medium" else ""))
    done = sum(1 for task in tasks if task["status"] == "done")
    lines.append(f"\n{len(tasks) - done} open, {done} done, {len(tasks)} total")
    return "\n".join(lines)


def render_panel(document: dict) -> list[str]:
    """One line per task, for a terminal side panel."""
    tasks = document.get("tasks") or []
    if not tasks:
        return ["(no tasks)"]
    marks = {"todo": "·", "doing": "▸", "blocked": "!", "done": "✓"}
    order = {"doing": 0, "blocked": 1, "todo": 2, "done": 3}
    rows = []
    for task in sorted(tasks, key=lambda item: (order.get(item["status"], 3), item["title"].lower())):
        marker = marks.get(task["status"], "·")
        star = "*" if task["priority"] == "high" else " "
        rows.append(f"{marker}{star} {task['title'][:44]}")
    done = sum(1 for task in tasks if task["status"] == "done")
    rows.append("")
    rows.append(f"{len(tasks) - done} open / {done} done")
    return rows


# -- bus ---------------------------------------------------------------------------------------------

class TaskListBus:
    """Poll the file, emit a snapshot when it changes, and notify immediately on local writes."""

    def __init__(self, path: Path = DEFAULT_PATH, interval: float = 0.4):
        self.path = Path(path)
        self.interval = interval
        self._subscribers: list = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._digest = self._file_digest()
        self._lock = threading.Lock()

    def _file_digest(self) -> str:
        try:
            stat = self.path.stat()
            return f"{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            return "missing"

    def subscribe(self, callback) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def snapshot(self) -> dict:
        return load(self.path)

    def emit(self, document: dict | None = None) -> None:
        document = document if document is not None else load(self.path)
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(document)
            except Exception:  # a broken renderer must not stop the bus
                continue

    def apply(self, text: str) -> dict:
        result = apply(text, self.path)
        self._digest = self._file_digest()
        if result.get("ok"):
            self.emit(result.get("document"))
        return result

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            digest = self._file_digest()
            if digest != self._digest:
                self._digest = digest
                self.emit()

    def start(self) -> "TaskListBus":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="task-list-bus", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None


# -- CLI ----------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Task list bus: render, command and watch task-list.json.")
    parser.add_argument("--path", default=str(DEFAULT_PATH), help="Task list file")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Print the list")
    add = sub.add_parser("add", help="Add a task")
    add.add_argument("title", nargs=argparse.REMAINDER)
    command = sub.add_parser("command", help="Run one AIML command, e.g. \"done 2\"")
    command.add_argument("text", nargs=argparse.REMAINDER)
    watch = sub.add_parser("watch", help="Print the panel again whenever the file changes")
    watch.add_argument("--seconds", type=float, default=0, help="Stop after N seconds (0 = until Ctrl+C)")

    args = parser.parse_args(argv)
    path = Path(args.path)

    if args.command == "list":
        print(render_text(load(path)))
        return 0
    if args.command == "add":
        text = " ".join(args.title).strip()
        if not text:
            print("task_list: a title is required", file=sys.stderr)
            return 2
        result = apply(f"ADD TASK {text}", path)
        print(result["reply"])
        return 0 if result["ok"] else 1
    if args.command == "command":
        text = " ".join(args.text).strip()
        result = apply(text, path)
        print(result["reply"])
        return 0 if result["ok"] else 1

    bus = TaskListBus(path).start()
    deadline = time.monotonic() + args.seconds if args.seconds else None
    try:
        print("\n".join(render_panel(bus.snapshot())) + "\n")
        bus.subscribe(lambda document: print("\n".join(render_panel(document)) + "\n"))
        while deadline is None or time.monotonic() < deadline:
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 0
    finally:
        bus.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
