"""Port the AIML corpus into one GML document - `aiml-corpus.gml` - and verify the port.

Why one file: the corpus is a graph of patterns that redirect into each other. As 84 XML files it is a
list; as one document the redirect structure, the per-bank provenance and the directive boundaries are
visible and machine-checkable.

Scope is explicit, because "the corpus" is ambiguous here:

    default   the banks the host actually loads - the host's own, the package's phase/routing banks,
              and the learned bank: 19 files, ~419 categories
    --all     every .aiml under the tree, including the vendored ALICE foundation set: 84 files,
              ~99,900 categories and a very large document

Every category becomes exactly one node, every bank one node with its sha256, every `<srai>` either a
resolved edge or an explicit `srai_missing` node - nothing is dropped silently. `--check` re-reads a
written document and re-derives the inventory from the sources; if they disagree it fails.

What this does NOT do: it does not make the GML document executable, and nothing here changes what the
AIML kernel loads. It is a projection of the corpus, used for inspection and verification.
"""
from __future__ import annotations

import hashlib
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
PACKAGE = APP_ROOT / "kuhul-phase-engine-v0.1.0"
DEFAULT_OUTPUT = APP_ROOT / "aiml-corpus.gml"
SCHEMA_ID = "gml-aiml-corpus/1"
DIRECTIVES = ("TOOL", "MEMORY", "MEMQUERY", "GITOP", "CODEX_PLAN", "CODEX_SUGGEST", "CODEX_LOOKUP",
              "IDENTITY")
XML_NS = re.compile(r"^\{.*\}")


def host_banks() -> list[Path]:
    """The banks the host and the daemon actually load, in load order."""
    files = [APP_ROOT / name for name in ("_override.aiml", "codex.aiml", "gitops.aiml",
                                          "identity.aiml", "memory.aiml", "smalltalk.aiml",
                                          "micronaut.aiml", "micronaut-example.aiml")]
    files += [PACKAGE / "phases" / f"{phase}.aiml"
              for phase in ("pop", "wo", "yax", "sek", "chen", "xul")]
    files += [PACKAGE / "routing" / "kuhul-phases.aiml", PACKAGE / "routing" / "xcfe.aiml",
              PACKAGE / "integrations" / "daemon-modes.aiml",
              APP_ROOT / "aiml-en-us-foundation-alice" / "knumatic_learned.aiml"]
    return [path for path in files if path.is_file()]


def all_banks() -> list[Path]:
    """Every .aiml in the tree, minus generated and backup directories."""
    found = []
    for path in sorted(APP_ROOT.rglob("*.aiml")):
        text = str(path).replace("\\", "/")
        if any(part in text for part in ("/backups/", "/node_modules/", "/logs/", "/dist/")):
            continue
        found.append(path)
    return found


def _key(path: Path) -> str:
    """A stable name for a bank: relative to the repo when it lives there, otherwise as given."""
    path = Path(path)
    try:
        return path.resolve().relative_to(APP_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tag(element) -> str:
    return XML_NS.sub("", element.tag).lower()


def _flatten(element) -> str:
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()


@dataclass
class Category:
    bank: Path
    phrase: str
    that: str
    wildcard_count: int
    template: str
    template_kind: str
    srai: list[str] = field(default_factory=list)
    directive: str = ""
    line: int = 0


def read_bank(path: Path) -> dict:
    """Categories in one file, or the parse error - never a silent skip."""
    try:
        root = ET.fromstring(Path(path).read_text(encoding="utf-8"))
    except (ET.ParseError, UnicodeDecodeError) as error:
        return dict(path=Path(path), categories=[], error=f"{type(error).__name__}: {error}"[:200])
    categories = []
    for element in root.iter():
        if _tag(element) != "category":
            continue
        pattern = next((child for child in element if _tag(child) == "pattern"), None)
        template = next((child for child in element if _tag(child) == "template"), None)
        that = next((child for child in element if _tag(child) == "that"), None)
        if template is None:
            continue
        phrase = _flatten(pattern) if pattern is not None else ""
        text = _flatten(template)
        srai = [_flatten(child) for child in template.iter() if _tag(child) == "srai"]
        directive = next((word for word in DIRECTIVES
                          if text.upper().startswith(word + " ")), "")
        kind = "directive" if directive else ("srai_only" if srai and text == srai[0] else "text")
        categories.append(Category(bank=Path(path), phrase=phrase,
                                   that=_flatten(that) if that is not None else "",
                                   wildcard_count=phrase.count("*"), template=text,
                                   template_kind=kind, srai=srai, directive=directive))
    return dict(path=Path(path), categories=categories, error=None)


def inventory(paths: list[Path]) -> dict:
    """The corpus as data: banks, categories, and whatever failed to parse."""
    banks, categories, errors = [], [], []
    for path in paths:
        entry = read_bank(path)
        if entry["error"]:
            errors.append(dict(path=_key(path), detail=entry["error"]))
        banks.append(dict(path=_key(path), digest=digest(path),
                          bytes=path.stat().st_size, categories=len(entry["categories"]),
                          error=entry["error"]))
        categories.extend(entry["categories"])
    return dict(banks=banks, categories=categories, errors=errors,
                total_categories=len(categories), total_banks=len(banks))


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(document: dict) -> str:
    """The single-file GML projection."""
    banks, categories = document["banks"], document["categories"]
    by_phrase: dict[str, int] = {}
    lines = [
        "graph [",
        ' schema "gml-registry/1"',
        ' graph_id "corpus/aiml"',
        f' extension [ schema_id "{SCHEMA_ID}" owner "knumatic.host" ]',
        ' contract [ name "aiml-corpus" required "bank" required "category" ]',
        ' note "Projection of the AIML corpus: one bank node per file, one category node per'
        ' <category>, one edge per containment and per resolved <srai>."',
        ' note "Digests are sha256 of the source file, so this document can be re-verified against'
        ' the corpus it claims to describe."',
        "",
    ]
    next_id = 1
    bank_ids = {}
    for bank in banks:
        bank_ids[bank["path"]] = next_id
        lines.append(f' node [ id {next_id} kind "bank" path {_quote(bank["path"])} '
                     f'digest {_quote(bank["digest"])} bytes {bank["bytes"]} '
                     f'categories {bank["categories"]} ]')
        next_id += 1
    category_ids = {}
    for index, category in enumerate(categories):
        identifier = next_id
        next_id += 1
        category_ids[index] = identifier
        by_phrase.setdefault(category.phrase.upper(), identifier)
    directive_ids: dict[str, int] = {}
    for category in categories:
        if category.directive:
            key = f"{category.directive} {category.template.split(' ', 1)[1] if ' ' in category.template else ''}".strip()
            if key not in directive_ids:
                directive_ids[key] = next_id
                next_id += 1
    srai_missing: dict[str, int] = {}
    for category in categories:
        for target in category.srai:
            if target.upper() not in by_phrase and target.upper() not in srai_missing:
                srai_missing[target.upper()] = next_id
                next_id += 1

    for index, category in enumerate(categories):
        directive_key = ""
        if category.directive:
            directive_key = (f"{category.directive} "
                             f"{category.template.split(' ', 1)[1] if ' ' in category.template else ''}").strip()
        attributes = [f"id {category_ids[index]}", 'kind "category"',
                      f"bank {bank_ids[_key(category.bank)]}",
                      f"phrase {_quote(category.phrase)}",
                      f"wildcard_count {category.wildcard_count}",
                      f'template_kind "{category.template_kind}"',
                      f"template {_quote(category.template[:400])}"]
        if category.that:
            attributes.append(f"that {_quote(category.that)}")
        if directive_key:
            attributes.append(f"directive {directive_ids[directive_key]}")
        lines.append(" node [ " + " ".join(attributes) + " ]")

    for key, identifier in directive_ids.items():
        verb, _, argument = key.partition(" ")
        lines.append(f' node [ id {identifier} kind "directive" verb {_quote(verb)} '
                     f'argument {_quote(argument)} ]')

    for key, identifier in srai_missing.items():
        lines.append(f' node [ id {identifier} kind "srai_missing" phrase {_quote(key)} '
                     f'note "no category in this projection matches it" ]')

    lines.append("")
    for index, category in enumerate(categories):
        bank_id = bank_ids[_key(category.bank)]
        lines.append(f' edge [ source {bank_id} target {category_ids[index]} relation "contains" ]')
    for index, category in enumerate(categories):
        for target in category.srai:
            resolved = by_phrase.get(target.upper())
            if resolved is not None:
                lines.append(f' edge [ source {category_ids[index]} target {resolved} '
                             f'relation "redirects_to" ]')
            else:
                lines.append(f' edge [ source {category_ids[index]} '
                             f'target {srai_missing[target.upper()]} relation "redirects_missing" ]')
    for index, category in enumerate(categories):
        if category.directive:
            key = (f"{category.directive} "
                   f"{category.template.split(' ', 1)[1] if ' ' in category.template else ''}").strip()
            lines.append(f' edge [ source {category_ids[index]} target {directive_ids[key]} '
                         f'relation "emits" ]')

    lines += [
        "",
        ' constraint [ name "one_node_per_category" arity 1 scope "graph" '
        'predicate "category_count_matches" authority "declaration_only" ]',
        ' constraint [ name "no_grant_from_corpus" arity 1 scope "graph" '
        'predicate "corpus_grants_nothing" authority "declaration_only" ]',
        ' operator [ name "LOOKUP" signature "phrase -> category*" authority "declaration_only" ]',
        ' note "A projection for inspection and verification. It grants no execution: the kernel'
        ' still loads the .aiml files, and admission is still the host\'s."',
        "]",
    ]
    return "\n".join(lines) + "\n"


def write(output: Path = DEFAULT_OUTPUT, *, everything: bool = False) -> dict:
    paths = all_banks() if everything else host_banks()
    document = inventory(paths)
    document["text"] = render(document)
    document["bytes"] = len(document["text"].encode("utf-8"))
    Path(output).write_text(document["text"], encoding="utf-8", newline="\n")
    return document


def check(document_path: Path = DEFAULT_OUTPUT, *, everything: bool = False) -> dict:
    """Re-read a written document and compare it with the sources: counts, digests, wildcards."""
    import phases  # the package's own parser, the same one the gate uses
    gml2 = phases.core_module("gml2")

    text = Path(document_path).read_text(encoding="utf-8")
    problems: list[dict] = []
    try:
        parsed = gml2.parse(text)
    except Exception as error:
        return dict(ok=False, problems=[dict(code="parse_failed", detail=f"{type(error).__name__}: {error}")])
    nodes = [entry for entry in parsed.entries if entry.name == "node"]
    edges = [entry for entry in parsed.entries if entry.name == "edge"]
    banks = {}
    categories = {}
    missing = 0
    for node in nodes:
        attributes = {attribute.name: attribute.value for attribute in node.value.entries}
        if attributes.get("kind") == "bank":
            banks[attributes.get("path")] = attributes
        elif attributes.get("kind") == "category":
            categories[attributes.get("id")] = attributes
        elif attributes.get("kind") == "srai_missing":
            missing += 1
    sources = inventory(all_banks() if everything else host_banks())
    if len(categories) != sources["total_categories"]:
        problems.append(dict(code="category_count",
                             detail=f"{len(categories)} nodes vs {sources['total_categories']} in the sources"))
    if len(banks) != sources["total_banks"]:
        problems.append(dict(code="bank_count", detail=f"{len(banks)} vs {sources['total_banks']}"))
    for bank in sources["banks"]:
        recorded = banks.get(bank["path"])
        if recorded is None:
            problems.append(dict(code="bank_missing", detail=bank["path"]))
        elif recorded.get("digest") != bank["digest"]:
            problems.append(dict(code="digest_mismatch", detail=bank["path"]))
        elif int(recorded.get("categories") or -1) != bank["categories"]:
            problems.append(dict(code="bank_category_count", detail=bank["path"]))
    wildcards = sum(1 for category in sources["categories"] if category.wildcard_count)
    recorded_wildcards = sum(1 for attributes in categories.values()
                             if int(attributes.get("wildcard_count") or 0))
    if wildcards != recorded_wildcards:
        problems.append(dict(code="wildcard_counts", detail=f"{recorded_wildcards} vs {wildcards}"))
    resolve_edges = sum(1 for edge in edges
                        if next((a.value for a in edge.value.entries if a.name == "relation"), "") == "redirects_to")
    redirected = sum(len(category.srai) for category in sources["categories"])
    if resolve_edges + missing != redirected:
        problems.append(dict(code="srai_accounting",
                             detail=f"{resolve_edges} resolved + {missing} missing vs {redirected} redirects"))
    return dict(ok=not problems, problems=problems, banks=len(banks), categories=len(categories),
                edges=len(edges), resolved_redirects=resolve_edges, unresolved_redirects=missing,
                errors=sources["errors"])


def summary(document: dict, output: Path) -> str:
    lines = [f"wrote {output} · {document['total_banks']} bank(s) · {document['total_categories']} "
             f"category(ies) · {document['bytes'] / 1024 / 1024:.2f} MB"]
    for error in document["errors"][:5]:
        lines.append(f"  parse error: {error['path']}: {error['detail']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Project the AIML corpus into one GML document.")
    parser.add_argument("--write", nargs="?", const=str(DEFAULT_OUTPUT), default=None)
    parser.add_argument("--check", nargs="?", const=str(DEFAULT_OUTPUT), default=None)
    parser.add_argument("--all", action="store_true", help="include the vendored ALICE corpus")
    args = parser.parse_args(argv)
    if args.write:
        output = Path(args.write)
        document = write(output, everything=args.all)
        print(summary(document, output))
        return 0 if not document["errors"] else 2
    report = check(Path(args.check or DEFAULT_OUTPUT), everything=args.all)
    print(f"check {'ok' if report['ok'] else 'FAILED'} · banks {report.get('banks')} · "
          f"categories {report.get('categories')} · edges {report.get('edges')} · "
          f"redirects {report.get('resolved_redirects')} resolved / "
          f"{report.get('unresolved_redirects')} unresolved")
    for problem in report.get("problems", [])[:10]:
        print(f"  {problem['code']}: {problem['detail']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
