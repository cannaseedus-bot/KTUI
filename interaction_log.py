"""One interaction log for every local LLM client.

The terminal (`task-engine.py`) and the chat app (`chat_app.py`) both call `log_interaction` after a
prompt is answered, and `pattern_dumper.py` reads the directory back to compile categories. Keeping
this in one module is the point: a new local client only has to call one function to be included, and
the dumper never has to know which app produced a record.

Record shape (one JSON object per line, one file per day):

    {"at": "2026-03-01T12:00:00+00:00", "app": "task-engine", "model": "qwen3-4b",
     "user": "how many aliases are there", "assistant": "6", "status": "ANSWERED", "tools": 1}

`user`/`assistant` is the canonical pair. `read_interactions` also accepts the terminal's older
`task`/`answer` transcripts, so history written before this module existed is still compiled.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# gpt-oss.toml sits next to this module, so its directory is the repository root: logs/ belongs
# there. (Resolving one level up would write outside the project, into the user profile.)
REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_DIR = REPO_ROOT / "logs" / "llm-interactions"
MAX_TEXT = 8000


def _clean(value: object, limit: int = MAX_TEXT) -> str:
    text = "" if value is None else str(value)
    return text.replace("\x00", " ").strip()[:limit]


def log_interaction(
    *,
    app: str,
    user: object,
    assistant: object,
    model: object | None = None,
    status: object | None = None,
    tools: int | None = None,
    path: Path | None = None,
) -> Path:
    """Append one prompt/response pair. Never raises: logging must not break the client."""
    directory = path or DEFAULT_DIR
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "app": _clean(app, 40) or "unknown",
        "model": _clean(model, 120) or None,
        "user": _clean(user),
        "assistant": _clean(assistant),
        "status": _clean(status, 40) or None,
        "tools": tools,
    }
    if not record["user"] or not record["assistant"]:
        return directory  # nothing worth learning from
    try:
        directory.mkdir(parents=True, exist_ok=True)
        file = directory / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
        with file.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return file
    except OSError:
        return directory


def read_interactions(*directories: Path) -> list[dict]:
    """Every recorded pair, newest first, from the interaction log and the terminal transcripts."""
    pairs: list[dict] = []
    for directory in directories:
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for file in sorted(directory.glob("*.jsonl"), reverse=True):
            try:
                lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                user = record.get("user") or record.get("task") or record.get("prompt")
                assistant = record.get("assistant") or record.get("answer") or record.get("response")
                if not user or not assistant:
                    continue  # tool-only or partial records
                pairs.append({
                    "task": _clean(user),
                    "answer": _clean(assistant),
                    "status": record.get("status"),
                    "app": record.get("app") or "task-engine",
                    "model": record.get("model"),
                    "source": file.name,
                })
    return pairs


def interaction_dirs(extra: list[str] | None = None) -> list[Path]:
    directories = [DEFAULT_DIR, REPO_ROOT / "logs" / "gpt-oss-terminal"]
    for item in extra or []:
        directories.append(Path(os.path.expanduser(str(item))))
    return directories
