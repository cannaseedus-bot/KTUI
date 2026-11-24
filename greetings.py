"""Greeting-µ: the greeting graph, loaded as data, used to decompose an utterance into routes.

A greeting is an entry point, not an answer. This module reads `greeting.gml`, splits an utterance
into clauses, and asks the graph where each clause leads - conversation, question, tool, command,
memory, task, identity - so "Hey, how are you, and can you check my server?" keeps all three intents
instead of collapsing to the greeting.

What it does not do: execute, authorize, or call a model. Every clause comes back as a *proposal*
with the authority the graph declares for its destination (`read_only`, `proposal_only`,
`requires_grant`). The host decides what to do with them, and that decision lives in the same
admission boundary as everything else.

Editing greeting.gml changes what this recognises, and that is asserted by a test - the document is the
declaration, this module only applies it.
"""
from __future__ import annotations

import re
from pathlib import Path

import phases

APP_ROOT = Path(__file__).resolve().parent
GRAPH_PATH = APP_ROOT / "greeting.gml"
GRAPH_SCHEMA = "gml-conversation/1"
CLAUSE_SPLIT = re.compile(r"(?<=[,.!?;:])\s+|\s+(?:and|then|also|plus)\s+|\s*&\s*", re.I)
AUTHORITIES = {"read_only", "proposal_only", "requires_grant"}


def _attr(node, name, default=None):
    for entry in getattr(node, "entries", []) or []:
        if getattr(entry, "name", "") == name:
            return entry.value
    return default


def load(path: Path = GRAPH_PATH) -> dict:
    """Parse the graph and check it: unique ids, declared authorities, edges that resolve."""
    try:
        gml2 = phases.core_module("gml2")
        document = gml2.parse(Path(path).read_text(encoding="utf-8"))
    except Exception as error:
        return dict(ok=False, problems=[dict(code="parse_failed", detail=f"{type(error).__name__}: {error}")],
                    nodes={}, edges=[], schema=None, graph_id=None)
    problems = []
    nodes, edges = {}, []
    schema = _attr(document, "schema")
    for entry in getattr(document, "entries", []) or []:
        if entry.name == "node":
            identifier = _attr(entry.value, "id")
            if not isinstance(identifier, int):
                problems.append(dict(code="node_id", detail=repr(identifier)))
                continue
            if identifier in nodes:
                problems.append(dict(code="duplicate_node", detail=str(identifier)))
            nodes[identifier] = dict(
                id=identifier, kind=_attr(entry.value, "kind"),
                phrase=_attr(entry.value, "phrase"), name=_attr(entry.value, "name"),
                authority=_attr(entry.value, "authority"), cues=_attr(entry.value, "cues"),
                meaning=_attr(entry.value, "meaning"))
        elif entry.name == "edge":
            edges.append(dict(source=_attr(entry.value, "source"),
                              target=_attr(entry.value, "target"),
                              relation=_attr(entry.value, "relation")))
    extension = next((entry for entry in getattr(document, "entries", []) or []
                      if entry.name == "extension"), None)
    declared_schema = _attr(extension.value, "schema_id") if extension else None
    if declared_schema != GRAPH_SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {GRAPH_SCHEMA}, got {declared_schema!r}"))
    for edge in edges:
        if edge["source"] not in nodes or edge["target"] not in nodes:
            problems.append(dict(code="edge_unresolved",
                                 detail=f"{edge['source']}->{edge['target']}"))
        if not isinstance(edge["relation"], str) or not edge["relation"]:
            problems.append(dict(code="edge_relation", detail="missing relation"))
    for node in nodes.values():
        if node["kind"] == "destination":
            if node["authority"] not in AUTHORITIES:
                problems.append(dict(code="authority", detail=f"{node['name']}: {node['authority']!r}"))
            if not node["name"]:
                problems.append(dict(code="destination_name", detail=str(node["id"])))
        if node["kind"] in ("greeting", "social") and not node["phrase"]:
            problems.append(dict(code="phrase_missing", detail=str(node["id"])))
    return dict(ok=not problems, problems=problems, nodes=nodes, edges=edges,
                schema=declared_schema, graph_id=_attr(document, "graph_id"),
                counts=dict(nodes=len(nodes), edges=len(edges)))


def phrases(kind: str, path: Path = GRAPH_PATH) -> list[str]:
    loaded = load(path)
    return sorted({node["phrase"] for node in loaded["nodes"].values() if node["kind"] == kind})


def destinations(path: Path = GRAPH_PATH) -> dict[str, dict]:
    loaded = load(path)
    return {node["name"]: node for node in loaded["nodes"].values() if node["kind"] == "destination"}


def reachable(greeting: str, path: Path = GRAPH_PATH) -> list[str]:
    """Which destinations the graph says one greeting may lead to."""
    loaded = load(path)
    by_phrase = {node["phrase"]: node["id"] for node in loaded["nodes"].values()
                 if node["kind"] in ("greeting", "social")}
    origin = by_phrase.get(greeting.strip().upper())
    if origin is None:
        return []
    return sorted({loaded["nodes"][edge["target"]]["name"] for edge in loaded["edges"]
                   if edge["source"] == origin and edge["target"] in loaded["nodes"]
                   and loaded["nodes"][edge["target"]]["kind"] == "destination"})


CONNECTOR = re.compile(r"^(?:and|then|also|plus|but|so)\b\s*", re.I)
FILLER = {"there", "again", "everyone", "all"}


def split(text: str) -> list[str]:
    """Clauses, in order, with the connecting words removed."""
    clauses = []
    for part in CLAUSE_SPLIT.split(text or ""):
        clause = CONNECTOR.sub("", part.strip(" .!?,;:")).strip()
        if clause and re.search(r"[A-Za-z0-9]", clause):
            clauses.append(clause)
    return clauses


def classify(clause: str, path: Path = GRAPH_PATH) -> dict:
    """Where one clause leads, according to the graph. A proposal, never an action."""
    loaded = load(path)
    upper = (clause or "").strip().upper()
    for node in loaded["nodes"].values():
        if node["kind"] in ("greeting", "social") and node["phrase"]:
            phrase = node["phrase"]
            if upper == phrase or upper.startswith(phrase + " "):
                # A greeting can open a clause that keeps going: "hey remember my dog's name".
                remainder = clause[len(phrase):].strip(" ,.!?-") if len(clause) > len(phrase) else ""
                if remainder.strip().lower() in FILLER:
                    remainder = ""
                return dict(clause=clause, kind=node["kind"], destination="conversation",
                            authority="read_only", phrase=phrase, remainder=remainder)
    words = set(re.findall(r"[A-Z]+", upper))
    best = None
    for node in loaded["nodes"].values():
        if node["kind"] != "destination":
            continue
        cues = [cue.strip() for cue in (node["cues"] or "").split(",") if cue.strip()]
        matched = [cue for cue in cues
                   if (len(cue.split()) > 1 and cue in upper)
                   or (len(cue.split()) == 1 and cue in words)]
        if not matched:
            continue
        # The most specific cue wins: "who are you" is identity, not the generic "who" question cue.
        score = max(len(cue) for cue in matched)
        if best is None or score > best[0]:
            best = (score, node)
    if best is not None:
        return dict(clause=clause, kind="destination", destination=best[1]["name"],
                    authority=best[1]["authority"], phrase=None)
    return dict(clause=clause, kind="other", destination="question", authority="read_only",
                phrase=None)


def routes(text: str, path: Path = GRAPH_PATH) -> dict:
    """The full decomposition: clauses, their destinations, and the declared authority of each."""
    loaded = load(path)
    intents = []
    for clause in split(text):
        intent = classify(clause, path)
        remainder = intent.pop("remainder", "")
        intents.append(intent)
        if remainder:
            # The greeting is the opener, not the whole message: keep what followed it.
            intents.append(classify(remainder, path))
    return dict(ok=loaded["ok"], schema=loaded["schema"], graph_id=loaded["graph_id"],
                graph=dict(nodes=loaded["counts"]["nodes"], edges=loaded["counts"]["edges"]),
                clauses=[intent["clause"] for intent in intents], intents=intents,
                multi=len(intents) > 1, authorized=False, problems=loaded["problems"])


def summary(path: Path = GRAPH_PATH) -> str:
    loaded = load(path)
    lines = [f"Greeting-µ: {loaded.get('graph_id')} · {loaded['counts']['nodes']} node(s) · "
             f"{loaded['counts']['edges']} edge(s) · {'valid' if loaded['ok'] else 'INVALID'}"]
    for problem in loaded["problems"][:6]:
        lines.append(f"  {problem['code']}: {problem['detail']}")
    greetings = ", ".join(phrases("greeting", path)) or "(none)"
    lines.append(f"  greetings: {greetings}")
    for name, node in sorted(destinations(path).items()):
        lines.append(f"  -> {name:<12} {node['authority']:<14} cues: {node['cues'] or '(none)'}")
    lines.append("")
    lines.append("A greeting selects routes; every destination is a proposal the host admits or refuses.")
    return "\n".join(lines)
