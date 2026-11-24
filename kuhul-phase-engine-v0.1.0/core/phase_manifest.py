"""`kuhul-phases/v1` manifests: one JSON file per phase, chained by schema URI.

A phase manifest is a small declaration, not a program:

```json
{
  "schema": "kuhul-phases/v1",
  "phase": "Pop",
  "uri": "kuhul://phases/pop",
  "aiml": ["../pop.aiml"],
  "bindings": [
    {"pattern": "WHO IS *", "srai": "WHAT IS {star:1}"},
    {"pattern": "TELL ME ABOUT MY DOG", "directive": "COMPOSE pet",
     "capability": "graph.relations.read"}
  ],
  "next": "kuhul://phases/wo"
}
```

`aiml` names pure AIML banks; `bindings` are AIML category bindings (a pattern that redirects to another
expression, or that emits a host directive). `next` chains to the next phase by **schema URI**, which
resolves inside the manifest set (`kuhul://phases/<name>` -> `<dir>/<name>.json`).

What this module guarantees: every manifest is checked against the phase vocabulary, every referenced
AIML file is reported missing rather than assumed, every binding's `{star:N}` is within the pattern's
wildcard count, and a chain that loops or repeats a phase is a bounded failure with the chain in the
message. Nothing is executed and no AIML is loaded from here - the loader only says what exists.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA = "kuhul-phases/v1"
PHASES = ("Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul")
PHASE_BY_LOWER = {"pop": "Pop", "wo": "Wo", "yax": "Yax", "sek": "Sek", "chen": "Ch'en",
                  "ch'en": "Ch'en", "xul": "Xul"}
SCHEMES = ("kuhul://phases/", "phases://", "kuhul://phase/")
MAX_CHAIN = 16


class ManifestError(ValueError):
    """A manifest that contradicts the schema or the phase vocabulary."""


def phase_of(word: str) -> str | None:
    return PHASE_BY_LOWER.get(str(word or "").strip().lower())


def uri_for(phase: str) -> str:
    return f"kuhul://phases/{str(phase).lower().replace(chr(39), '')}"


def _resolve_uri(uri: str, root: Path) -> Path:
    """`kuhul://phases/wo` -> `<root>/wo.json`. An unknown scheme is an error, not a guess."""
    text = str(uri or "").strip()
    for scheme in SCHEMES:
        if text.startswith(scheme):
            name = text[len(scheme):].strip("/")
            if not name or "/" in name:
                raise ManifestError(f"a phase uri names exactly one phase: {uri!r}")
            return Path(root) / f"{name.lower()}.json"
    if text.endswith(".json") and "/" not in text:
        return Path(root) / text
    raise ManifestError(f"unsupported chain uri {uri!r} (expected one of {', '.join(SCHEMES)})")


def _wildcards(pattern: str) -> int:
    return str(pattern or "").count("*")


def load(path: Path, *, root: Path | None = None, check_files: bool = True) -> dict:
    """Parse and validate one manifest. Returns the record plus any problems."""
    path = Path(path)
    root = Path(root) if root is not None else path.parent
    problems: list[dict] = []
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, path=str(path), problems=[
            dict(code="unreadable", detail=f"{type(error).__name__}: {error}")], manifest={})
    if not isinstance(record, dict):
        return dict(ok=False, path=str(path), problems=[
            dict(code="not_an_object", detail=path.name)], manifest={})

    if record.get("schema") != SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {SCHEMA}, got {record.get('schema')!r}"))
    phase = phase_of(record.get("phase"))
    if phase is None:
        problems.append(dict(code="phase", detail=f"unknown phase {record.get('phase')!r}"))
    declared_uri = record.get("uri")
    if declared_uri is not None and not isinstance(declared_uri, str):
        problems.append(dict(code="uri", detail=f"uri must be a string, got {type(declared_uri).__name__}"))
    elif declared_uri is not None and phase is not None and declared_uri != uri_for(phase):
        problems.append(dict(code="uri_mismatch", detail=f"{declared_uri!r} != {uri_for(phase)!r}"))

    aiml = record.get("aiml") or []
    if not isinstance(aiml, list) or any(not isinstance(item, str) for item in aiml):
        problems.append(dict(code="aiml", detail="aiml must be a list of relative paths"))
        aiml = []
    missing = []
    for name in aiml:
        candidate = (path.parent / name).resolve()
        if check_files and not candidate.is_file():
            missing.append(name)
    if missing:
        problems.append(dict(code="aiml_missing", detail=", ".join(missing)))

    bindings = record.get("bindings") or []
    if not isinstance(bindings, list):
        problems.append(dict(code="bindings", detail="bindings must be a list"))
        bindings = []
    for index, binding in enumerate(bindings):
        if not isinstance(binding, dict):
            problems.append(dict(code="binding_shape", detail=f"#{index} is not an object"))
            continue
        pattern = binding.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            problems.append(dict(code="binding_pattern", detail=f"#{index} has no pattern"))
            continue
        target = binding.get("srai") or binding.get("directive")
        if not isinstance(target, str) or not target.strip():
            problems.append(dict(code="binding_target",
                                 detail=f"{pattern!r} has neither srai nor directive"))
        for match in re.finditer(r"\{star:(\d+)\}", str(target or "")):
            if int(match.group(1)) > _wildcards(pattern):
                problems.append(dict(code="binding_capture",
                                     detail=f"{pattern!r} has {_wildcards(pattern)} wildcard(s) "
                                            f"but the target asks for star:{match.group(1)}"))

    next_uri = record.get("next")
    if next_uri is not None and not isinstance(next_uri, str):
        problems.append(dict(code="next", detail="next must be a string uri or null"))
        next_uri = None

    return dict(ok=not problems, path=str(path), problems=problems,
                manifest=dict(schema=record.get("schema"), phase=phase, uri=declared_uri,
                              aiml=list(aiml), missing=missing, bindings=bindings,
                              next=next_uri, authority=record.get("authority", "declaration_only")),
                root=str(root))


def chain(start: str | Path, *, root: Path | None = None, check_files: bool = True) -> dict:
    """Follow `next` from one manifest to the end, bounded, with cycles reported as cycles."""
    root = Path(root) if root is not None else Path(start).parent
    first = Path(start) if str(start).endswith(".json") else _resolve_uri(str(start), root)
    visited: list[str] = []
    manifests: list[dict] = []
    problems: list[dict] = []
    phases: list[str] = []
    current = first
    while True:
        if len(visited) >= MAX_CHAIN:
            problems.append(dict(code="chain_too_long", detail=f"more than {MAX_CHAIN} manifests"))
            break
        loaded = load(current, root=root, check_files=check_files)
        if not loaded["ok"]:
            problems += loaded["problems"]
            break
        manifest = loaded["manifest"]
        key = str(Path(current).resolve())
        if key in visited:
            problems.append(dict(code="chain_cycle",
                                 detail=" -> ".join(visited + [key])))
            break
        visited.append(key)
        manifests.append(manifest)
        if manifest["phase"]:
            if manifest["phase"] in phases:
                problems.append(dict(code="phase_repeated", detail=manifest["phase"]))
            phases.append(manifest["phase"])
        if not manifest["next"]:
            break
        try:
            current = _resolve_uri(manifest["next"], root)
        except ManifestError as error:
            problems.append(dict(code="chain_uri", detail=str(error)))
            break
    return dict(ok=not problems, problems=problems, phases=phases, chain=visited,
                manifests=manifests, root=str(root),
                aiml=[name for manifest in manifests for name in manifest["aiml"]],
                bindings=sum(len(manifest["bindings"]) for manifest in manifests),
                authority="declaration_only")


def discover(folder: Path) -> dict:
    """Every manifest in a folder, in phase order when they are all present."""
    folder = Path(folder)
    found = {}
    for path in sorted(folder.glob("*.json")):
        loaded = load(path, root=folder, check_files=False)
        phase = loaded["manifest"].get("phase")
        if phase:
            found.setdefault(phase, []).append(loaded)
    duplicates = {phase: len(items) for phase, items in found.items() if len(items) > 1}
    problems = [problem for items in found.values() for item in items for problem in item["problems"]]
    if duplicates:
        problems.append(dict(code="duplicate_phase", detail=str(sorted(duplicates))))
    return dict(ok=not problems, problems=problems,
                phases=[phase for phase in PHASES if phase in found],
                manifests={phase: [item["path"] for item in items]
                           for phase, items in found.items()})


def summary(report: dict) -> str:
    if not report["chain"]:
        reasons = "; ".join(problem["detail"] for problem in report["problems"][:3])
        return f"no chain: {reasons or 'nothing to load'}"
    lines = [f"kuhul-phases/v1 chain: {' -> '.join(report['phases'])} "
             f"({len(report['chain'])} manifest(s), {len(report['aiml'])} aiml file(s), "
             f"{report['bindings']} binding(s))"]
    for problem in report["problems"][:6]:
        lines.append(f"  {problem['code']}: {problem['detail']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Inspect a kuhul-phases/v1 manifest chain.")
    parser.add_argument("folder", help="directory holding pop.json, wo.json, ...")
    parser.add_argument("--start", default="kuhul://phases/pop")
    args = parser.parse_args(argv)
    report = chain(args.start, root=Path(args.folder))
    print(summary(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
