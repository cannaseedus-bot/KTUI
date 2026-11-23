#!/usr/bin/env python3
"""Mirror the PLAN.md regression ledger into `task-list.json`, so the UI can see the guards (M7).

PLAN.md is the canonical ledger; `task-list.json` is rendered state. This script reads the task
table out of PLAN.md and reconciles two kinds of entries:

  ledger tasks   titled `<ID> — <task>`; their status follows the ledger (done/guard -> done,
                 open -> todo) and their note carries the ledger's evidence cell
  human tasks    everything else in the file, left exactly as it is

It is idempotent: running it twice changes nothing the second time, and it never deletes a task the
ledger does not know about.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import task_list

APP_ROOT = Path(__file__).resolve().parent
PLAN = APP_ROOT / "PLAN.md"
LEDGER_ID = re.compile(r"^([FM]\d+) — ")
ROW = re.compile(r"^\|\s*([FM]\d+)\s*\|\s*(.+?)\s*\|\s*\*{0,2}([a-z]+)\*{0,2}\s*\|\s*(.+?)\s*\|\s*$")
STATUS = {"done": "done", "guard": "done", "open": "todo", "erased": "blocked"}


def ledger_rows(path: Path = PLAN) -> list[dict]:
    """The task table from PLAN.md, in file order."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = ROW.match(line.strip())
        if not match:
            continue
        identifier, task, status, where = match.groups()
        rows.append(dict(id=identifier, task=task.strip(), status=status.lower(),
                         note=f"ledger: {status.lower()} · {where.strip()}"))
    return rows


def mirror(document: dict, rows: list[dict]) -> dict:
    """Reconcile the document with the ledger rows, leaving unrelated tasks untouched.

    Idempotent: a row that is already mirrored with the same title, status and note keeps its record
    byte for byte, so running the mirror twice is a no-op and the file only changes when the ledger
    does.
    """
    tasks = list(document.get("tasks") or [])
    existing = {task.get("id"): task for task in tasks if LEDGER_ID.match(task.get("title", ""))}
    kept = [task for task in tasks if not LEDGER_ID.match(task.get("title", ""))]
    stamp = datetime.now(timezone.utc).isoformat()
    mirrored = []
    for row in rows:
        identifier = row["id"].lower()
        candidate = {
            "id": identifier,
            "title": f"{row['id']} — {row['task']}"[:task_list.MAX_TITLE],
            "status": STATUS.get(row["status"], "todo"),
            "priority": "high" if row["status"] == "open" else "medium",
            "note": row["note"][:200],
        }
        previous = existing.get(identifier)
        if previous and all(previous.get(key) == value for key, value in candidate.items()
                            if key not in {"id"}):
            mirrored.append(previous)          # unchanged: keep its timestamps exactly
            continue
        mirrored.append(candidate | {"created_at": (previous or {}).get("created_at") or stamp,
                                     "updated_at": stamp})
    document["tasks"] = mirrored + kept
    return document


def main(argv: list[str] | None = None) -> int:
    path = Path(argv[0]) if argv else task_list.DEFAULT_PATH
    rows = ledger_rows()
    if not rows:
        print(f"no ledger rows found in {PLAN.name}", file=sys.stderr)
        return 1
    document = task_list.load(path)
    before = json.dumps(document.get("tasks"), sort_keys=True)
    mirror(document, rows)
    open_work = sum(1 for row in rows if row["status"] == "open")
    if json.dumps(document.get("tasks"), sort_keys=True) == before:
        # No write when nothing changed: the bus polls file digests, so a no-op save is pure noise.
        print(f"ledger mirror already current: {len(rows)} row(s), {open_work} open")
        return 0
    task_list.save(document, path)
    print(f"mirrored {len(rows)} ledger row(s) into {path}: {open_work} open")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
