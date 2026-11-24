"""Cheap staleness signalling: a counter the projection bumps, so a poll can skip rebuilding entirely.

Stage 1 compared a semantic digest after rebuilding the whole projection - correct, but it pays for every
registry read on every tick. This is stage 2's cheap gate:

    Lifecycle.ensure / acquire / release / release_idle   bump
    evidence_record.append                                bump
    chat_app.poll_runtime                                 compare first, rebuild only when it moved

The counter is a *hint*, never a source of truth: a bump with no semantic change still passes through the
digest check before the widget repaints, and a missed bump costs one stale frame, not a wrong one. Nothing
here wakes, leases or stops anything.
"""
from __future__ import annotations

import threading

SCHEMA = "kuhul://runtime-signals/v1"
_lock = threading.Lock()
_generation = 0
_reason = "start"


def bump(reason: str = "change") -> int:
    """Record that something observable may have changed. Cheap, thread-safe, read-only elsewhere."""
    global _generation, _reason
    with _lock:
        _generation += 1
        _reason = str(reason or "change")
        return _generation


def generation() -> int:
    with _lock:
        return _generation


def state() -> dict:
    with _lock:
        return dict(schema=SCHEMA, generation=_generation, reason=_reason)


def reset(reason: str = "reset") -> int:
    """Test helper: put the counter back to zero so a scenario starts from a known generation."""
    global _generation, _reason
    with _lock:
        _generation = 0
        _reason = str(reason)
        return _generation
