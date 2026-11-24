"""AIML → GML round trip: migrate real categories, validate the graph, and compare behaviour.

The claim under test is not "the labels survive" but "the behaviour survives":

    AIML category  ->  GML graph  ->  validated by the package  ->  match  ->  SRAI  ->  rendered output
                                                                    |
                                                          compared with python-aiml

Four node roles are kept distinct, as the review requires: `pattern` (expression + wildcard count),
`template` (ordered segments), `category` (the relationship between them, with provenance) and `srai`
(a redirect expression with `max_depth`/`visited_guard`). The category is a relationship object, not a
node carrying the words.

Scope is honest: patterns using only literals and `*` are migrated. A pattern with `<that>`, a topic,
or a construct this matcher does not implement is *reported as unsupported* and skipped, never quietly
approximated.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import phases
import srai_resolver

APP_ROOT = Path(__file__).resolve().parent
SCHEMA = "aiml-gml/1"
WILDCARD = "*"
WILD_ONE = "_"
STAR = re.compile(r"\{star:(\d+)\}")


def _tag(element) -> str:
    return element.tag.split("}")[-1].lower()


def _flatten(element) -> str:
    return re.sub(r"\s+", " ", "".join(element.itertext()) or "").strip()


def _flatten_with_stars(element) -> str:
    """Flatten an element, turning `<star index="n"/>` into the `{star:n}` redirect placeholder."""
    pieces = [element.text or ""]
    for child in element:
        name = _tag(child)
        if name == "star":
            pieces.append("{star:%s}" % child.attrib.get("index", "1"))
        elif name == "srai":
            pieces.append(_flatten_with_stars(child))
        else:
            pieces.append(_flatten(child))
        pieces.append(child.tail or "")
    return re.sub(r"\s+", " ", "".join(pieces)).strip()


@dataclass
class Migrated:
    """One category, in both representations, with its provenance."""

    origin: str
    index: int
    pattern: str
    segments: list[dict] = field(default_factory=list)
    srai: str = ""
    template_text: str = ""
    unsupported: str = ""

    @property
    def category_id(self) -> str:
        return f"{self.origin}:{self.index}"

    @property
    def wildcard_count(self) -> int:
        return self.pattern.count(WILDCARD)

    @property
    def is_redirect(self) -> bool:
        return bool(self.srai)


def read_categories(path: Path) -> list[Migrated]:
    """Categories in one file, in file order, with their provenance."""
    try:
        root = ET.fromstring(Path(path).read_text(encoding="utf-8"))
    except (ET.ParseError, UnicodeDecodeError):
        return []
    origin = Path(path).name
    found = []
    for index, element in enumerate(element for element in root.iter() if _tag(element) == "category"):
        pattern = next((child for child in element if _tag(child) == "pattern"), None)
        template = next((child for child in element if _tag(child) == "template"), None)
        that = next((child for child in element if _tag(child) == "that"), None)
        topic = next((child for child in element if _tag(child) == "topic"), None)
        if pattern is None or template is None:
            continue
        migrated = Migrated(origin=origin, index=index, pattern=_flatten(pattern),
                            template_text=_flatten(template))
        if that is not None or topic is not None:
            migrated.unsupported = "the/topic context"
        srai = next((child for child in template.iter() if _tag(child) == "srai"), None)
        if srai is not None:
            migrated.srai = _flatten_with_stars(srai)
        # Segments in document order: the template's own text, then each child with its tail text.
        ordinal = 0
        leading = re.sub(r"\s+", " ", template.text or "").strip()
        if leading:
            migrated.segments.append(dict(ordinal=ordinal, kind="text", value=leading))
            ordinal += 1
        for child in template:
            name = _tag(child)
            if name == "srai":
                migrated.segments.append(dict(ordinal=ordinal, kind="redirect",
                                              value=_flatten_with_stars(child)))
                ordinal += 1
            elif name == "star":
                migrated.segments.append(dict(ordinal=ordinal, kind="capture",
                                              index=int(child.attrib.get("index", "1"))))
                ordinal += 1
            else:
                inner = _flatten(child)
                if inner:
                    migrated.segments.append(dict(ordinal=ordinal, kind="text", value=inner))
                    ordinal += 1
            tail = re.sub(r"\s+", " ", child.tail or "").strip()
            if tail:
                migrated.segments.append(dict(ordinal=ordinal, kind="text", value=tail))
                ordinal += 1
        if not migrated.segments:
            migrated.unsupported = "empty template"
        found.append(migrated)
    return found


# -- GML emission ------------------------------------------------------------------------------------
def _quote(text) -> str:
    value = "" if text is None else str(text)
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_gml(category: Migrated) -> str:
    """One category as its own `aiml-gml/1` graph, with the four distinct node roles."""
    graph_id = f"category/{category.origin}/{category.index}"
    nodes = [
        f' node [ id 0 kind "category" category_id {_quote(category.category_id)} '
        f'pattern_ref "aiml://pattern/{category.origin}/{category.index}#1" '
        f'template_ref "aiml://template/{category.origin}/{category.index}#2" ]',
        f' node [ id 1 kind "pattern" expression {_quote(category.pattern)} '
        f'wildcard_count {category.wildcard_count} match_type "aiml" ]',
    ]
    if category.is_redirect:
        nodes.append(f' node [ id 2 kind "template" output_type "redirect" ]')
        nodes.append(f' node [ id 3 kind "srai" expression {_quote(category.srai)} '
                     f'max_depth 3 visited_guard 1 ]')
    else:
        nodes.append(f' node [ id 2 kind "template" output_type "text" ]')
        for segment in category.segments:
            if segment["kind"] == "capture":
                nodes.append(f' node [ id {2 + segment["ordinal"] + 1} kind "segment" '
                             f'ordinal {segment["ordinal"]} segment_kind "capture" '
                             f'capture_index {segment["index"]} ]')
            elif segment["kind"] == "text":
                nodes.append(f' node [ id {2 + segment["ordinal"] + 1} kind "segment" '
                             f'ordinal {segment["ordinal"]} segment_kind "text" '
                             f'value {_quote(segment["value"])} ]')
    return "\n".join(["graph [", ' schema "aiml-gml/1"', f' graph_id {_quote(graph_id)}',
                      ' contract "category"', *nodes, "]"])


def to_segments_block(category: Migrated) -> str:
    """The package's own template shape: `segment [ ordinal kind value/index ]` inside the node."""
    parts = []
    for segment in category.segments:
        if segment["kind"] == "capture":
            parts.append(f'segment [ ordinal {segment["ordinal"]} kind "capture" '
                         f'index {segment["index"]} ]')
        elif segment["kind"] == "text":
            parts.append(f'segment [ ordinal {segment["ordinal"]} kind "text" '
                         f'value {_quote(segment["value"])} ]')
    return " ".join(parts)


def to_bundle(categories: list[Migrated]) -> dict:
    """The migrated set as the package's six contracts, so the real validator can check it."""
    patterns, templates, categories_gml, redirects = [], [], [], []
    next_id = {"pattern": 1, "template": 1, "category": 1, "srai": 1}
    for category in categories:
        if category.unsupported:
            continue
        pattern_id = next_id["pattern"]
        next_id["pattern"] += 1
        patterns.append(f'node [ id {pattern_id} kind "pattern" '
                        f'expression {_quote(category.pattern)} '
                        f'wildcard_count {category.wildcard_count} ]')
        template_id = next_id["template"]
        next_id["template"] += 1
        if category.is_redirect:
            templates.append(f'node [ id {template_id} kind "template" output_type "redirect" '
                             f'segment [ ordinal 0 kind "redirect" ] ]')
        else:
            templates.append(f'node [ id {template_id} kind "template" output_type "text" '
                             f'{to_segments_block(category)} ]')
        category_node = next_id["category"]
        next_id["category"] += 1
        categories_gml.append(
            f'node [ id {category_node} kind "category" '
            f'pattern_ref "aiml://pattern/main#{pattern_id}" '
            f'template_ref "aiml://template/main#{template_id}" '
            f'category_id {_quote(category.category_id)} ]')
        if category.is_redirect:
            srai_id = next_id["srai"]
            next_id["srai"] += 1
            redirects.append(f'node [ id {srai_id} kind "srai" '
                             f'expression {_quote(category.srai)} max_depth 3 visited_guard 1 ]')
    documents = {
        "pattern/main": f'graph [ schema "aiml-gml/1" graph_id "pattern/main" contract "pattern" '
                        f'{" ".join(patterns)} ]',
        "template/main": f'graph [ schema "aiml-gml/1" graph_id "template/main" contract "template" '
                         f'{" ".join(templates)} ]',
        "category/main": f'graph [ schema "aiml-gml/1" graph_id "category/main" contract "category" '
                         f'{" ".join(categories_gml)} ]',
        "srai/main": f'graph [ schema "aiml-gml/1" graph_id "srai/main" contract "srai" '
                     f'{" ".join(redirects) or "node [ id 1 kind \"srai\" expression \"X\" max_depth 3 visited_guard 1 ]"} ]',
        "retrieval/main": 'graph [ schema "aiml-gml/1" graph_id "retrieval/main" contract "retrieval" '
                          'node [ id 1 kind "retrieval" ] ]',
        "composition/main": 'graph [ schema "aiml-gml/1" graph_id "composition/main" '
                            'contract "composition" node [ id 1 kind "composition" ] ]',
    }
    gml2 = phases.core_module("gml2")
    return {name: gml2.parse(text) for name, text in documents.items()}


def validate(categories: list[Migrated]) -> dict:
    """Run the migrated set through the package's real bundle validator and the rule predicates."""
    extension_module = phases.core_module("extension")
    bundle_module = phases.core_module("aiml_bundle")
    gml2 = phases.core_module("gml2")
    problems: list[dict] = []
    graphs = to_bundle(categories)
    try:
        extension = extension_module.load_extension(gml2.parse(
            (phases.ROOT / "schemas" / "aiml-registry.gml").read_text(encoding="utf-8")))
        state = bundle_module.Bundle(graphs, extension).validate()
    except Exception as error:
        return dict(ok=False, state="REJECTED", problems=[
            dict(code="bundle", detail=f"{type(error).__name__}: {error}"[:300])])
    for category in categories:
        if category.unsupported:
            problems.append(dict(code="unsupported", detail=f"{category.category_id}: "
                                                           f"{category.unsupported}"))
    return dict(ok=True, state=state, problems=problems,
                migrated=sum(1 for item in categories if not item.unsupported),
                unsupported=[item.category_id for item in categories if item.unsupported])


# -- runtime: match, srai, render --------------------------------------------------------------------
def normalize(text: str) -> str:
    return re.sub(r"[^A-Z0-9* _]+", " ", (text or "").upper()).strip()


def tokenize(text: str) -> list[str]:
    """Tokens with punctuation stripped and case preserved: captures must keep the user's case."""
    return re.sub(r"[^A-Za-z0-9* _]+", " ", text or "").split()


def match(pattern: str, text: str) -> list[str] | None:
    """AIML-style match with `*` captures. Matching is case-insensitive, captures are not."""
    pattern_tokens = [token.upper() for token in tokenize(pattern)]
    original = tokenize(text)
    text_tokens = [token.upper() for token in original]
    captures: list[str] = []

    def walk(pi: int, ti: int) -> bool:
        if pi == len(pattern_tokens):
            return ti == len(text_tokens)
        token = pattern_tokens[pi]
        if token in (WILDCARD, WILD_ONE):
            minimum = 1 if token == WILDCARD else 1
            maximum = len(text_tokens) - ti
            for size in range(maximum, minimum - 1, -1):
                captures.append(" ".join(original[ti:ti + size]))
                if walk(pi + 1, ti + size):
                    return True
                captures.pop()
            return False
        if ti < len(text_tokens) and text_tokens[ti] == token:
            return walk(pi + 1, ti + 1)
        return False

    return captures if walk(0, 0) else None


def render(category: Migrated, captures: list[str]) -> str:
    """Compose the template: text segments and captures in ordinal order."""
    parts = []
    for segment in sorted(category.segments, key=lambda item: item["ordinal"]):
        if segment["kind"] == "text":
            parts.append(segment["value"])
        elif segment["kind"] == "capture":
            index = segment["index"]
            parts.append(captures[index - 1] if 1 <= index <= len(captures) else "")
        elif segment["kind"] == "redirect":
            return srai_resolver.substitute(segment["value"], captures)
    return " ".join(parts).strip()


def answer(categories: list[Migrated], text: str, *, max_depth: int = 3) -> dict:
    """Match, follow SRAI within bounds, and render. Never executes anything."""
    usable = [item for item in categories if not item.unsupported]
    trace: list[dict] = []

    def hop(current: str, depth: int, seen: set) -> dict:
        if depth > max_depth:
            return dict(ok=False, reason=f"max_depth {max_depth} exceeded", trace=trace)
        key = normalize(current)
        if key in seen:
            return dict(ok=False, reason=f"SRAI loop at {current!r}", trace=trace)
        seen.add(key)
        for category in usable:
            captures = match(category.pattern, current)
            if captures is None:
                continue
            trace.append(dict(depth=depth, category=category.category_id,
                              pattern=category.pattern, captures=captures))
            if category.is_redirect:
                redirected = srai_resolver.substitute(category.srai, captures)
                return hop(redirected, depth + 1, seen)
            return dict(ok=True, reply=render(category, captures),
                        category=category.category_id, trace=trace)
        return dict(ok=False, reason="no matching category", trace=trace)

    return hop(text or "", 0, set())


def summary(result: dict) -> str:
    if not result.get("ok"):
        return f"no answer: {result.get('reason')}"
    return f"{result['reply']}  (via {result['category']}, {len(result['trace'])} hop(s))"
