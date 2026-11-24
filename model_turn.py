"""The model turn as three observable handlers: process, validate, close.

Streaming is work, but finishing a stream is not verification. This module draws the three lines the observer needs,
and keeps them apart:

    process    the completed stream becomes a candidate        transport failure is its own outcome
    validate   the candidate is examined                        structural acceptance, labelled as such
    close      the turn ends with an outcome and two booleans   emitted and verified are different facts

The vocabulary is deliberately narrow: `verdict` is one of accepted / refused / empty / tool_call / transport_failed.
`verified` means the candidate was examined, not that it is true. A successfully displayed refusal is `refused`,
`emitted: true`, `ok: false` - the emission worked and the turn did not succeed.
"""
from __future__ import annotations

import re

SCHEMA = "kuhul://model-turn/v1"
VERDICTS = ("accepted", "refused", "empty", "tool_call", "transport_failed")
OUTCOMES = ("accepted", "refused", "failed")
# A refusal is a legitimate answer, so it must be recognisable rather than inferred from length.
REFUSAL = re.compile(
    r"^\s*(?:i\s+(?:cannot|can't|can not|won't|will not|am unable|'m unable)"
    r"|i'm (?:sorry|unable|afraid)"
    r"|that (?:isn't|is not|isn't something)\b"
    r"|sorry,? (?:but )?i\b)", re.I)


def process(*, text: str, chunks: int = 0, error: Exception | None = None) -> dict:
    """Sek: the completed stream, as a candidate. Nothing here decides whether the answer is any good."""
    if error is not None:
        return dict(schema=SCHEMA, hop="process", ok=False, transport="failed",
                    reason=f"{type(error).__name__}: {error}"[:200], chunks=chunks,
                    chars=len(text or ""))
    return dict(schema=SCHEMA, hop="process", ok=True, transport="ok", reason=None, chunks=chunks,
                chars=len(text or ""))


def validate(text: str, *, tool_calls: bool = False, error: Exception | None = None) -> dict:
    """Ch'en: examine the candidate. Structural and labelled - not a claim that the answer is correct."""
    if error is not None:
        return dict(schema=SCHEMA, hop="validate", verdict="transport_failed", verified=False, ok=False,
                    transport="failed", reason="the stream did not complete")
    body = (text or "").strip()
    if not body and not tool_calls:
        return dict(schema=SCHEMA, hop="validate", verdict="empty", verified=False, ok=False,
                    transport="ok", reason="the stream completed with no content")
    if tool_calls:
        return dict(schema=SCHEMA, hop="validate", verdict="tool_call", verified=True, ok=True,
                    transport="ok", reason="the model asked for a tool rather than answering")
    if REFUSAL.match(body):
        return dict(schema=SCHEMA, hop="validate", verdict="refused", verified=True, ok=False,
                    transport="ok", reason="the model declined; that is an answer, not a failure to answer")
    return dict(schema=SCHEMA, hop="validate", verdict="accepted", verified=True, ok=True,
                transport="ok", reason=None)


def close(verdict: str, *, emitted: bool) -> dict:
    """Xul: the turn ends. Emission success and turn success are separate booleans."""
    if verdict not in VERDICTS:
        return dict(schema=SCHEMA, hop="close", ok=False, emitted=bool(emitted), verified=False,
                    outcome="failed", reason=f"{verdict!r} is not a verdict")
    outcome = {"accepted": "accepted", "tool_call": "accepted", "refused": "refused"}.get(verdict, "failed")
    return dict(schema=SCHEMA, hop="close", outcome=outcome, emitted=bool(emitted),
                verified=verdict in ("accepted", "refused", "tool_call"),
                ok=bool(emitted) and outcome == "accepted",
                reason=None if emitted else "the answer was not displayed")


def summary(result: dict) -> str:
    hop = result.get("hop")
    if hop == "process":
        return (f"Sek · process · transport {result['transport']} · {result['chunks']} chunk(s) · "
                f"{result['chars']} char(s)")
    if hop == "validate":
        return (f"Ch'en · validate · {result['verdict']} · verified {result['verified']} · ok {result['ok']}")
    if hop == "close":
        return (f"Xul · close · {result['outcome']} · emitted {result['emitted']} · "
                f"verified {result['verified']} · ok {result['ok']}")
    return f"model turn · {hop}"
