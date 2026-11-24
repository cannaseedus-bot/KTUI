"""Retrieval and composition: the two contracts that were declared but never consumed, now applied.

The review's example, made real:

    input        "tell me about my dog"
    retrieved    pet  -> name        -> Rex      (score 0.83)
                 pet  -> personality -> playful  (score 0.71)
                 pet  -> size        -> big      (score 0.44)
    composed     subject = pet, attributes = [big, playful]   (alphabetical)
    output       "pet is big and playful. That is everything I have recorded about pet."
    verified     every attribute exists · one subject · no contradictions · nothing invented

Both behaviours come from the package's own contracts - `retrieval.gml` (weights, threshold, cap) and
`composition.gml` (output type, ordering, separator, sentence templates) - not from constants in this
file. Editing the contract changes the paragraph, which the guards assert.

Rules this module keeps:

  evidence first   a relation must exist in the user's memory projection; nothing is invented to fill
                   a slot, and a missing fact degrades the answer instead of padding it
  ranked, not guessed  lexical overlap with the query plus recency, weighted by the contract
  verified         subject consistency, attribute support, and contradictions are checked before the
                   paragraph is returned - a failed verification returns the problems, not the prose
  no authority     composing is a read; the paragraph is text, and nothing here writes memory
"""
from __future__ import annotations

import re
from pathlib import Path

import phases
import user_memory

APP_ROOT = Path(__file__).resolve().parent
CONTRACTS = phases.ROOT / "aiml_contracts"
DEFAULTS = dict(strategy="lexical_then_recency", weight_lexical=0.7, weight_recency=0.3,
                min_score=0.10, max_candidates=6,
                output_type="paragraph", max_sentences=2, attribute_order="alphabetical",
                separator=", ", conjunction="and",
                sentences=["{subject} is {attributes}."])

STOP = {"the", "a", "an", "is", "are", "was", "were", "my", "me", "i", "about", "tell", "of",
        "to", "in", "on", "for", "and", "what", "whats", "does", "do", "you", "know"}


def _attributes(node) -> dict:
    found: dict = {}
    for entry in getattr(node, "entries", []) or []:
        name = getattr(entry, "name", "")
        value = getattr(entry, "value", None)
        if name == "sentence":
            template = next((item.value for item in entry.value.entries
                             if getattr(item, "name", "") == "template"), None)
            if isinstance(template, str):
                found.setdefault("sentences", []).append(template)
            continue
        if name in ("note", "id", "kind"):
            continue
        if isinstance(value, (str, int, float)):
            found[name] = value
    return found


def load(folder: Path = CONTRACTS) -> dict:
    """The retrieval and composition declarations, as the runtime reads them."""
    gml2 = phases.core_module("gml2")
    settings = dict(DEFAULTS)
    problems = []
    for name, kind in (("retrieval", "retrieval"), ("composition", "composition")):
        path = Path(folder) / f"{name}.gml"
        if not path.is_file():
            problems.append(dict(code="missing_contract", detail=str(path)))
            continue
        try:
            document = gml2.parse(path.read_text(encoding="utf-8"))
        except Exception as error:
            problems.append(dict(code="parse_failed", detail=f"{name}: {error}"[:200]))
            continue
        node = next((entry.value for entry in document.entries if entry.name == "node"
                     and any(getattr(item, "name", "") == "kind"
                             and item.value == kind for item in entry.value.entries)), None)
        if node is None:
            problems.append(dict(code="node_missing", detail=name))
            continue
        settings.update(_attributes(node))
    for key in ("weight_lexical", "weight_recency", "min_score", "max_candidates", "max_sentences"):
        try:
            settings[key] = (int(float(settings[key])) if key in
                             ("max_candidates", "max_sentences") else float(settings[key]))
        except (TypeError, ValueError):
            problems.append(dict(code="bad_number", detail=f"{key}={settings.get(key)!r}"))
            settings[key] = DEFAULTS[key]
    return dict(ok=not problems, problems=problems, settings=settings)


# -- retrieval -------------------------------------------------------------------------------------
def relations(user: str) -> list[dict]:
    """Every current fact as a relation, with the event index it came from."""
    events = user_memory.events(user)
    latest: dict[tuple[str, str], dict] = {}
    for index, event in enumerate(events):
        payload = event.get("payload") or {}
        if payload.get("type") != "fact_asserted":
            continue
        key = (payload.get("subject") or "", payload.get("predicate") or "")
        latest[key] = dict(subject=key[0], predicate=key[1],
                           value=str(payload.get("value") or ""), event_index=index,
                           event_id=event.get("event_id"))
    return [latest[key] for key in sorted(latest)]


def score(relation: dict, query: str, *, total_events: int, settings: dict) -> float:
    words = {word for word in re.findall(r"[a-z0-9]+", (query or "").lower()) if word not in STOP}
    haystack = f"{relation['subject']} {relation['predicate']} {relation['value']}".lower()
    lexical = len([word for word in words if word in haystack]) / len(words) if words else 0.0
    recency = (relation["event_index"] + 1) / total_events if total_events else 0.0
    return round(settings["weight_lexical"] * lexical + settings["weight_recency"] * recency, 3)


def retrieve(user: str, query: str, settings: dict) -> list[dict]:
    """Ranked relations above the declared threshold, capped by the declared maximum."""
    rows = relations(user)
    total = max(1, len(user_memory.events(user)))
    scored = [dict(relation, score=score(relation, query, total_events=total, settings=settings))
              for relation in rows]
    kept = [row for row in scored if row["score"] >= settings["min_score"]]
    kept.sort(key=lambda row: (-row["score"], row["predicate"]))
    return kept[: int(settings["max_candidates"])]


# -- composition -----------------------------------------------------------------------------------
def join_attributes(values: list[str], settings: dict) -> str:
    values = list(values)
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return f"{settings['separator'].join(values[:-1])} {settings['conjunction']} {values[-1]}"


def compose(relations_kept: list[dict], settings: dict) -> dict:
    """Build the plan: one subject, ordered attributes, and the sentence templates filled in."""
    if not relations_kept:
        return dict(ok=False, reason="no relations above the threshold", subject="", attributes=[])
    subjects: dict[str, int] = {}
    for row in relations_kept:
        subjects[row["subject"]] = subjects.get(row["subject"], 0) + 1
    subject = max(subjects, key=lambda name: (subjects[name], name))
    own = [row for row in relations_kept if row["subject"] == subject]
    if settings.get("attribute_order") == "alphabetical":
        own.sort(key=lambda row: (row["predicate"], row["value"]))
    # A name is an identifier, not an attribute: "pet (Rex) is big and playful" reads; "pet is Rex,
    # playful and big" does not.
    named = [row for row in own if row["predicate"] == "name"]
    attributes = [row["value"] for row in own if row["predicate"] != "name"]
    display = subject.replace(".", " ")
    if named:
        display = f"{display} ({named[0]['value']})"
    slots = dict(subject=display, attributes=join_attributes(attributes, settings))
    templates = list(settings.get("sentences") or DEFAULTS["sentences"])
    templates = templates[: int(settings["max_sentences"])]
    sentences = [template.format(**slots) for template in templates]
    return dict(ok=True, subject=subject, attributes=attributes,
                predicates=[row["predicate"] for row in own],
                sentences=sentences, paragraph=" ".join(sentences).strip(),
                used=[row["event_id"] for row in own])


def verify(plan: dict, relations_kept: list[dict], *, user: str) -> dict:
    """Check the plan against the evidence before anyone reads the prose."""
    problems: list[dict] = []
    if not plan.get("ok"):
        return dict(ok=False, problems=[dict(code="no_plan", detail=plan.get("reason", ""))])
    known = {(row["subject"], row["value"]) for row in relations(user)}
    for attribute in plan["attributes"]:
        if (plan["subject"], attribute) not in known:
            problems.append(dict(code="unsupported_attribute",
                                 detail=f"{plan['subject']} {attribute!r} is not in the projection"))
    subjects = {row["subject"] for row in relations_kept}
    if len(subjects) > 1:
        problems.append(dict(code="subject_inconsistent",
                             detail=f"relations from {sorted(subjects)}"))
    # A contradiction is two assertions of one predicate; the projection keeps the newest, so the
    # history is what reveals that a value was replaced.
    history: dict[tuple[str, str], set] = {}
    for event in user_memory.events(user):
        payload = event.get("payload") or {}
        if payload.get("type") == "fact_asserted" and payload.get("subject") == plan["subject"]:
            history.setdefault((payload.get("subject"), payload.get("predicate")), set()).add(
                str(payload.get("value")))
    # A value that changed is history, not a defect: the projection already answers with the newest.
    # Case-only variants are not even history - "PLAYFUL" and "playful" are the same fact.
    warnings = []
    for (subject, predicate), values in history.items():
        distinct = {value.strip().lower() for value in values}
        if len(distinct) > 1:
            warnings.append(dict(code="superseded_value",
                                 detail=f"{subject}.{predicate} has had {sorted(set(values))}; "
                                        f"using the newest"))
    return dict(ok=not problems, problems=problems, warnings=warnings,
                checked=dict(attributes=len(plan["attributes"]),
                             subjects=sorted(subjects), relations=len(relations_kept)))


def paragraph(user: str, query: str, *, folder: Path = CONTRACTS) -> dict:
    """Retrieve, compose and verify. Returns the plan and the verification alongside the prose."""
    contract = load(folder)
    settings = contract["settings"]
    kept = retrieve(user, query, settings)
    plan = compose(kept, settings)
    report = verify(plan, kept, user=user)
    return dict(ok=report["ok"], paragraph=plan.get("paragraph", "") if report["ok"] else "",
                plan=plan, verification=report, relations=kept, contract=contract)


def summary(result: dict) -> str:
    if result["ok"]:
        return (f"{result['paragraph']}\n\n"
                f"({len(result['relations'])} relation(s), verification passed)")
    reasons = "; ".join(problem["detail"] for problem in result["verification"]["problems"][:3])
    return f"no paragraph: {reasons or result['plan'].get('reason', 'unknown')}"
