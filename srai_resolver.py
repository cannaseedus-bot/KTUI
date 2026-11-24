"""Runtime enforcement of SRAI redirects: capture substitution, depth, and a visited set.

The static validator (the package's `rules.py`) can only check that a redirect *declares* its
safeguards - `max_depth` and `visited_guard 1` - and that a dynamic expression does not use a static
`@redirects_to` edge. It cannot decide whether a particular conversation loops, because the target of
`WHAT IS {star:1}` depends on what the user typed.

So the loop guard has to be a runtime property, and this module is it:

  substitute()  fill captures into the redirect expression
  resolve()     follow the redirect chain, bounded by max_depth and by a visited set keyed on the
                *resolved* expression plus its captures - the state a static traversal cannot see

It resolves and reports; it never executes anything. The caller supplies the lookup, which is where
authority would live.
"""
from __future__ import annotations

import re

CAPTURE = re.compile(r"\{star:(\d+)\}")


class SraiCycle(ValueError):
    """A redirect that repeats or exceeds its declared depth."""


def substitute(expression: str, captures: list[str] | tuple[str, ...]) -> str:
    """Fill `{star:N}` captures (1-based, as AIML numbers them) into a redirect expression."""
    def fill(match):
        index = int(match.group(1))
        if 1 <= index <= len(captures):
            return str(captures[index - 1])
        raise SraiCycle(f"capture {index} requested but only {len(captures)} provided")
    return CAPTURE.sub(fill, expression or "")


def is_redirect(reply: str) -> bool:
    """A reply that is itself a redirect, in either declared form."""
    text = (reply or "").strip()
    return text.upper().startswith("SRAI ") or bool(CAPTURE.search(text))


def resolve(expression: str, captures: list[str] | tuple[str, ...], lookup, *,
            max_depth: int = 3, visited_guard: int = 1) -> dict:
    """Follow a redirect chain. Returns the trace and the final reply, or raises SraiCycle.

    `lookup(text)` answers one hop; a reply that is itself a redirect continues the chain. The
    visited set holds `(expression, captures)` pairs, so a loop that only appears after substitution
    is still caught.
    """
    if max_depth is not None and max_depth <= 0:
        raise SraiCycle("max_depth must be positive")
    if not visited_guard:
        raise SraiCycle("a redirect requires visited_guard 1 to be enforced")
    seen: set[tuple[str, tuple[str, ...]]] = set()
    trace: list[dict] = []
    current, current_captures, depth = expression, tuple(captures or ()), 0
    while True:
        key = (current, current_captures)
        if visited_guard and key in seen:
            chain = " -> ".join(f"{hop['expression']}" for hop in trace) or current
            raise SraiCycle(f"SRAI loop detected: {chain} -> {current}")
        seen.add(key)
        if depth >= max_depth:
            raise SraiCycle(f"SRAI depth {depth} reached max_depth {max_depth} at {current!r}")
        resolved = substitute(current, current_captures)
        reply = lookup(resolved)
        trace.append(dict(depth=depth, expression=current, captures=list(current_captures),
                          resolved=resolved, reply=reply))
        if not is_redirect(reply):
            return dict(reply=reply, trace=trace, depth=depth)
        current = reply.strip()
        if current.upper().startswith("SRAI "):
            current = current[5:].strip()
        # Captures carry forward: a hop that still holds {star:N} is filled from the same input, which
        # is what makes a substituted loop visible (the guard keys on expression *and* captures).
        depth += 1


def summary(expression: str, captures=(), lookup=None, *, max_depth: int = 3) -> str:
    """A one-screen report, for /srai-style inspection."""
    try:
        outcome = resolve(expression, list(captures), lookup or (lambda text: text),
                          max_depth=max_depth)
    except SraiCycle as error:
        return f"SRAI refused: {error}"
    lines = [f"SRAI {expression!r} · {outcome['depth']} hop(s)"]
    for hop in outcome["trace"]:
        lines.append(f"  {hop['depth']}: {hop['expression']} -> {hop['resolved']} -> {hop['reply']!r}")
    return "\n".join(lines)
