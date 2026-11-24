"""`phase.resolve_aiml`: one category reference in, one typed phase plan out - read-only.

This is the integration point the review asked for, and nothing more than that. It does not become
another reasoning engine: it asks the components that already exist for what they know, and arranges
the answers into the six phases.

    Pop    what matched            aiml_graph.match over the migrated categories
    Wo     what was bound          captures, ELIZA field selection, conversation context
    Yax    where it could go       srai_resolver routes, vector candidates, graph facts
    Sek    what is proposed        map / filter / fold proposals over the candidates
    Ch'en  what is supported       evidence, unsupported claims, admission status
    Xul    what may be said        a closure that distinguishes known from unknown

Determinism is a contract: the plan contains no timestamps, no ordering that depends on hash seeds, and
two calls on the same input produce identical JSON. Execution authority stays with the host - the plan
carries `execution: false` and `authority: "declaration_only"`, and it never writes memory, admits a
proposal, or renders a final answer as if it had been verified elsewhere.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import aiml_graph
import greetings
import srai_resolver
import user_memory

APP_ROOT = Path(__file__).resolve().parent
SCHEMA = "kuhul.phase-plan/1"
PHASES = ("Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul")
QUESTION_WORDS = ("why", "how", "what", "who", "where", "when", "which")
EXPLAIN = ("why", "how")

# ELIZA-style reflection: the substitutions that turn the user's words into the system's fields.
# One direction only: the user's words reflected into the system's fields. Applying both directions
# would undo itself ("my" -> "your" -> "my").
REFLECTION = ((r"\bi'm\b", "you are"), (r"\bI\b", "you"), (r"\bmy\b", "your"),
              (r"\bme\b", "you"), (r"\bmine\b", "yours"), (r"\bam\b", "are"))
FIELDS = ("subject", "attributes", "question_type", "cause", "polarity")
TRAILING = {"like", "act", "be", "do", "does", "look", "seem", "sound", "get"}


def eliza_fields(text: str) -> dict:
    """Field selection, not a conversation engine: subject, attributes and question type."""
    lowered = str(text or "").strip().lower()
    words = re.findall(r"[a-z0-9']+", lowered)
    question = next((word for word in words if word in QUESTION_WORDS), "")
    reflected = lowered
    for pattern, replacement in REFLECTION:
        reflected = re.sub(pattern, replacement, reflected)
    # "bill's big black dog" -> subject "bill's dog", attributes [big, black]
    adjectives = []
    for word in words:
        if word in {"big", "small", "black", "white", "brown", "playful", "friendly", "lazy",
                    "furry", "old", "young", "loud", "quiet"}:
            adjectives.append(word)
    subject = ""
    possessive = re.search(r"([a-z']+)'s\s+(?:(?:big|small|black|white|brown|playful|friendly|lazy|"
                           r"furry|old|young|loud|quiet)\s+)*([a-z]+)", lowered)
    mine = re.search(r"\bmy\s+([a-z]+)", lowered)
    if possessive:
        subject = f"{possessive.group(1)}'s {possessive.group(2)}"
    elif mine and mine.group(1) not in TRAILING:
        subject = mine.group(1)
    return dict(question_type=("explanation" if question in EXPLAIN else
                               "identification" if question in ("what", "who")
                               else "description" if question else "statement"),
                question_word=question, subject=subject, attributes=sorted(set(adjectives)),
                reflected=reflected.strip(), fields=FIELDS)


def _categories() -> list:
    """The migrated categories, loaded once."""
    global _CACHE
    if _CACHE is None:
        banks = ("identity.aiml", "smalltalk.aiml", "memory.aiml", "gitops.aiml", "_override.aiml")
        categories = []
        for bank in banks:
            path = APP_ROOT / bank
            if path.is_file():
                categories += aiml_graph.read_categories(path)
        _CACHE = [item for item in categories if not item.unsupported]
    return _CACHE


_CACHE: list | None = None


def _facts(user: str) -> list[dict]:
    return compose_relations(user)


def compose_relations(user: str) -> list[dict]:
    """The user's current facts, without importing the composition module's contract loading."""
    events = user_memory.events(user)
    latest: dict[tuple[str, str], dict] = {}
    for index, event in enumerate(events):
        payload = event.get("payload") or {}
        if payload.get("type") != "fact_asserted":
            continue
        key = (payload.get("subject") or "", payload.get("predicate") or "")
        latest[key] = dict(index=index, subject=key[0], predicate=key[1],
                           value=str(payload.get("value") or ""),
                           event_id=event.get("event_id"))
    return [latest[key] for key in sorted(latest)]


DIRECTIVES = ("TOOL", "MEMORY", "MEMQUERY", "GITOP", "COMPOSE", "IDENTITY", "CODEX_PLAN",
              "CODEX_SUGGEST", "CODEX_LOOKUP")


def _is_directive(category) -> bool:
    """A template that asks the host to do something rather than saying something."""
    head = str(getattr(category, "template_text", "") or "").strip().upper()
    return any(head == verb or head.startswith(verb + " ") for verb in DIRECTIVES)


def _pop(text: str) -> dict:
    matched = []
    for category in _categories():
        captures = aiml_graph.match(category.pattern, text)
        if captures is None:
            continue
        matched.append(dict(pattern=category.pattern, category=category.category_id,
                            captures=captures, redirect=bool(category.is_redirect),
                            directive=_is_directive(category),
                            srai=category.srai or None,
                            wildcards=category.wildcard_count))
    intent = greetings.routes(text)
    return dict(matched=matched,
                candidate_intents=[item["destination"] for item in intent.get("intents") or []],
                matched_patterns=[item["pattern"] for item in matched])


def _wo(text: str, fields: dict, pop: dict) -> dict:
    captures = [capture for item in pop["matched"] for capture in item["captures"]]
    return dict(captures=sorted(set(captures)), fields=fields,
                conversation=dict(intents=[item["destination"] for item in
                                           (greetings.routes(text).get("intents") or [])]))


def _yax(text: str, pop: dict, *, retriever=None) -> dict:
    routes = []
    for item in pop["matched"]:
        if not item["srai"]:
            continue
        try:
            outcome = srai_resolver.resolve(item["srai"], item["captures"],
                                            lambda hop: _lookup(hop), max_depth=3)
        except srai_resolver.SraiCycle as error:
            routes.append(dict(pattern=item["pattern"], srai=item["srai"],
                               status="REFUSED", reason=str(error)))
            continue
        routes.append(dict(pattern=item["pattern"], srai=item["srai"], status="RESOLVED",
                           resolved=outcome["trace"][-1]["resolved"] if outcome["trace"] else None,
                           reply=outcome["reply"], hops=outcome["depth"] + 1))
    vectors = []
    if retriever is not None:
        try:
            vectors = retriever(text)
        except Exception as error:  # a retrieval failure is data, not a crash
            vectors = [dict(status="ERROR", detail=f"{type(error).__name__}: {error}")]
    return dict(srai_routes=routes, vector_candidates=vectors, graph_facts=[])


def _lookup(hop: str) -> str:
    """One hop of SRAI: an exact category match returns its template, otherwise no answer."""
    for category in _categories():
        if aiml_graph.match(category.pattern, hop) is not None and not category.is_redirect:
            return category.segments[0]["value"] if category.segments else ""
    return ""


def _sek(facts: list[dict], fields: dict) -> dict:
    """Operator proposals over the facts the user actually has. Nothing is applied here."""
    # Do not pre-filter by the asked subject: an ELIZA field is a guess, and dropping the user's facts
    # on the strength of a guess is how a system silently answers "I know nothing". Ch'en decides
    # which subject the facts belong to and reports it when the asked one is not recorded.
    relevant = list(facts)
    proposals = [
        dict(opcode="filter", lane="facts", argument="subject", keeps=len(relevant)),
        dict(opcode="map", lane="facts", argument="predicate -> proposition",
             count=len(relevant)),
        dict(opcode="fold", lane="propositions", argument="single paragraph", count=len(relevant)),
    ]
    return dict(operator_plan=proposals, relevant=relevant, candidates=len(facts))


def _chen(text: str, fields: dict, facts: list[dict], sek: dict) -> dict:
    """What the evidence supports, and what it does not - the distinction AIML alone cannot make."""
    recorded = sorted({fact["subject"] for fact in sek["relevant"]})
    asked = (fields.get("subject") or "").strip().lower()
    subject_used = next((name for name in recorded
                         if asked and (asked.endswith(name) or name in asked)), "")
    problems = []
    if asked and not subject_used:
        problems.append(dict(code="subject_not_recorded",
                             detail=f"{asked!r} is not in the recorded subjects {recorded}"))
    if not subject_used and recorded:
        subject_used = recorded[0]
    own = [fact for fact in sek["relevant"] if not subject_used or fact["subject"] == subject_used]
    attributes = [fact["value"] for fact in own if fact["predicate"] != "name"]
    evidence = [dict(kind="attribute", subject=fact["subject"], predicate=fact["predicate"],
                     value=fact["value"], event_id=fact["event_id"]) for fact in own]
    if not facts:
        problems.append(dict(code="no_facts", detail="nothing recorded for this user"))
    if fields["question_type"] == "explanation":
        causes = [fact for fact in facts if fact["predicate"].startswith("cause")]
        if not causes:
            problems.append(dict(code="unsupported_explanation",
                                 detail="the cause is not recorded, only the attribute"))
    wildcard_problems = [dict(code="wildcard_mismatch", detail=item["pattern"])
                        for item in _POP_CACHE.get("matched") or []
                        if len(item["captures"]) != item["wildcards"]]
    problems += wildcard_problems[:2]
    return dict(evidence=evidence, attributes=attributes, subject_used=subject_used,
                problems=problems,
                admitted=False, authority="declaration_only",
                checked=dict(relations=len(facts), attributes=len(attributes),
                             question_type=fields["question_type"]))


_POP_CACHE: dict = {}


def _xul(fields: dict, chen: dict, sek: dict, pop: dict) -> dict:
    attributes = chen["attributes"]
    unsupported = [problem for problem in chen["problems"]
                   if problem["code"] == "unsupported_explanation"]
    subject = chen.get("subject_used") or fields.get("subject") or "it"
    if any(item.get("directive") for item in pop["matched"]) or \
            "identity" in (pop.get("candidate_intents") or []):
        # A directive (IDENTITY, TOOL, MEMORY, GITOP, COMPOSE) belongs to the host: the plan says so
        # rather than re-rendering it from memory.
        return dict(closure="delegated", response="", verified=False, admitted=False, persist=False,
                    note="the host owns this answer; a phase plan does not re-render directives")
    if fields.get("question_type") == "statement":
        # "hello" is not a question: the bank answers it, and a phase plan should not pretend the
        # user asked about their dog.
        return dict(closure="none", response="", verified=False, admitted=False, persist=False,
                    note="no question in the input; nothing to close")
    if unsupported and attributes:
        closure = "partial"
        text = (f"{subject} is described as {', '.join(attributes)}, but there is no recorded cause "
                f"for that behaviour.")
    elif attributes:
        closure = "supported"
        text = f"{subject} is described as {', '.join(attributes)}."
    else:
        closure = "unknown"
        text = "Nothing recorded supports an answer to that yet."
    return dict(closure=closure, response=text, verified=closure == "supported",
                admitted=False, persist=False)


def resolve_aiml(text: str, *, user: str = "local-user", context: dict | None = None,
                 retriever=None, facts: list[dict] | None = None) -> dict:
    """One input -> the six-phase plan. Deterministic, read-only, and honest about its limits."""
    text = str(text or "").strip()
    fields = eliza_fields(text)
    facts = compose_relations(user) if facts is None else facts
    pop = _pop(text)
    _POP_CACHE.clear()
    _POP_CACHE.update(pop)
    wo = _wo(text, fields, pop)
    yax = _yax(text, pop, retriever=retriever)
    yax["graph_facts"] = facts
    sek = _sek(facts, fields)
    chen = _chen(text, fields, facts, sek)
    xul = _xul(fields, chen, sek, pop)
    plan = dict(schema=SCHEMA, input=text, user=user, context=dict(context or {}),
                phases=dict(Pop=pop, Wo=wo, Yax=yax, Sek=sek, **{"Ch'en": chen}, Xul=xul),
                order=list(PHASES), execution=False, mutation=False,
                authority="declaration_only",
                note="a plan is a proposal; the host decides what to run and what to say")
    return plan


def canonical(plan: dict) -> str:
    """Stable serialization: the same input must produce identical bytes."""
    return json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def summary(plan: dict) -> str:
    phases = plan["phases"]
    verify = phases["Ch'en"]
    close = phases["Xul"]
    lines = [f"phase plan · {plan['input']!r}",
             f"  Pop    {len(phases['Pop']['matched'])} candidate(s): "
             f"{', '.join(phases['Pop']['matched_patterns'][:3]) or '(none)'}",
             f"  Wo     subject={phases['Wo']['fields']['subject']!r} "
             f"attributes={phases['Wo']['fields']['attributes']}",
             f"  Yax    {len(phases['Yax']['srai_routes'])} redirect(s) · "
             f"{len(phases['Yax']['vector_candidates'])} vector(s) · "
             f"{len(phases['Yax']['graph_facts'])} fact(s)",
             f"  Sek    {len(phases['Sek']['operator_plan'])} operator proposal(s) · "
             f"{phases['Sek']['candidates']} candidate(s)",
             f"  Ch'en  {len(verify['evidence'])} evidence · {len(verify['problems'])} problem(s)",
             f"  Xul    {close['closure']}: {close['response']}",
             "  (execution false · authority declaration_only)"]
    return "\n".join(lines)
