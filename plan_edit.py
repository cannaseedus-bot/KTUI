"""Write a milestone section and prove it landed - the lesson from a silent no-op.

Twice in this project a patch reported success while `PLAN.md` was unchanged, because the insertion anchor had
gone stale and `str.replace` politely returned the original text. A successful write is not evidence that the
intended content changed.

So: every section carries a **stable marker**, the writer asserts the marker occurs **exactly once** afterwards,
and the byte count must move. The M-numbers are display labels; the marker is the identity.
"""
from __future__ import annotations

import re
from pathlib import Path


class PlanEditError(ValueError):
    """The write did not do what the caller claimed."""


def marker_for(identifier: str) -> str:
    """A stable, machine-checkable identity for one section."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(identifier).strip().lower()).strip("-")
    if not slug:
        raise PlanEditError(f"cannot build a marker from {identifier!r}")
    return f"<!-- milestone:{slug} -->"


def count(text: str, marker: str) -> int:
    return text.count(marker)


def insert_section(path: Path, identifier: str, section: str, *,
                   before: str | None = None) -> dict:
    """Insert a marked section exactly once, verifying the file afterwards."""
    path = Path(path)
    before_text = path.read_text(encoding="utf-8")
    marker = marker_for(identifier)
    if count(before_text, marker) == 1:
        return dict(inserted=False, marker=marker, size=len(before_text),
                    reason="the section is already present")
    if count(before_text, marker) > 1:
        raise PlanEditError(f"{marker} appears {count(before_text, marker)} times before writing")
    body = f"{marker}\n{section.strip()}\n\n"
    if before and before in before_text:
        after_text = before_text.replace(before, body + before, 1)
        where = f"before {before[:40]!r}"
    else:
        after_text = before_text.rstrip() + "\n\n" + body
        where = "appended"
    path.write_text(after_text, encoding="utf-8", newline="\n")
    written = path.read_text(encoding="utf-8")
    occurrences = count(written, marker)
    if occurrences != 1:
        raise PlanEditError(f"{marker} appears {occurrences} times after writing")
    if marker not in written or len(written) <= len(before_text):
        raise PlanEditError("the write did not change the file")
    return dict(inserted=True, marker=marker, where=where,
                size_before=len(before_text), size_after=len(written),
                occurrences=occurrences)
