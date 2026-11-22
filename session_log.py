"""Session transcripts: one JSONL file per conversation, so a session can be resumed or rewound.

`interaction_log.py` mines prompt/answer pairs into AIML; that is a knowledge feed and it does not
care which conversation a pair came from. This module is the other direction - going *back*:

  - the user can list past sessions, resume one, or rewind the current one a few exchanges,
  - the model can search what has already been said in earlier sessions instead of asking again.

One file per session, one message per line, append-only while the session is live. Rewinding and
resuming rewrite the file from the in-memory transcript rather than counting lines, so a truncated
or half-written record can never desynchronise memory from disk.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SESSIONS_DIR = REPO_ROOT / "logs" / "sessions"
MAX_TEXT = 20000
MAX_READ_BYTES = 8 * 1024 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_session() -> str:
    """A sortable id: the clock first, so a plain directory listing is chronological."""
    return f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


def _folder(directory: Path | None) -> Path:
    """Resolve the session folder at call time, so a caller can redirect it (tests, other roots)."""
    return Path(directory) if directory else SESSIONS_DIR


def path_for(session: str, directory: Path | None = None) -> Path:
    safe = "".join(character for character in session if character.isalnum() or character in "-_")
    if not safe:
        raise ValueError("session id has no usable characters")
    return _folder(directory) / f"{safe}.jsonl"


def append(session: str, role: str, content: object, *, model: object = None, directory: Path | None = None) -> Path:
    """Append one message. Never raises: losing a log line must not break the conversation."""
    file = path_for(session, directory)
    text = ("" if content is None else str(content))[:MAX_TEXT]
    if not text.strip():
        return file
    record = {"at": now(), "session": session, "role": role, "content": text}
    if model:
        record["model"] = str(model)[:120]
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return file


def _records(file: Path) -> list[dict]:
    try:
        if file.stat().st_size > MAX_READ_BYTES:
            return []
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("role") in {"user", "assistant"} and record.get("content"):
            records.append(record)
    return records


def files(directory: Path | None = None) -> list[Path]:
    """Every session file, newest first."""
    folder = _folder(directory)
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)


def sessions(limit: int = 20, directory: Path | None = None) -> list[dict]:
    """Summaries for `/sessions`: id, when it started and ended, how many turns, first question."""
    summaries = []
    for file in files(directory)[: max(0, limit)]:
        records = _records(file)
        if not records:
            continue
        first_user = next((record["content"] for record in records if record["role"] == "user"), "")
        summaries.append({
            "id": file.stem,
            "path": str(file),
            "turns": sum(1 for record in records if record["role"] == "assistant"),
            "messages": len(records),
            "started": records[0].get("at") or "",
            "ended": records[-1].get("at") or "",
            "preview": " ".join(first_user.split())[:80],
        })
    return summaries


def latest(directory: Path | None = None) -> str:
    found = sessions(limit=1, directory=directory)
    return found[0]["id"] if found else ""


def load(session: str, directory: Path | None = None) -> list[dict]:
    """The transcript of one session: [{"role", "content", "at"}, ...] oldest first."""
    return _records(path_for(session, directory))


def rewrite(session: str, messages: list[dict], *, model: object = None, directory: Path | None = None) -> int:
    """Replace the file with exactly these messages. Returns how many were written.

    Rewind, resume and a fresh session all funnel through here, so the file is always a faithful
    copy of what the conversation actually is.
    """
    file = path_for(session, directory)
    lines = []
    stamp = now()
    for message in messages:
        role = str(message.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        text = ("" if message.get("content") is None else str(message.get("content")))[:MAX_TEXT]
        if not text.strip():
            continue
        record = {"at": message.get("at") or stamp, "session": session, "role": role, "content": text}
        if model and message.get("model"):
            record["model"] = str(message["model"])[:120]
        elif model:
            record["model"] = str(model)[:120]
        lines.append(json.dumps(record, ensure_ascii=False))
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", newline="\n")
    except OSError:
        return 0
    return len(lines)


def search(text: str, *, limit: int = 10, directory: Path | None = None) -> list[dict]:
    """Messages containing `text`, newest session first. Empty query -> the most recent messages."""
    needle = (text or "").strip().lower()
    found: list[dict] = []
    for file in files(directory):
        records = _records(file)
        for record in reversed(records):
            if needle and needle not in record["content"].lower():
                continue
            found.append({
                "session": file.stem,
                "role": record["role"],
                "at": record.get("at") or "",
                "content": " ".join(record["content"].split()),
            })
            if len(found) >= max(1, limit):
                return found
        if not needle and found:
            return found[:limit]
    return found[:limit]


def delete(session: str, directory: Path | None = None) -> bool:
    try:
        path_for(session, directory).unlink()
        return True
    except OSError:
        return False
