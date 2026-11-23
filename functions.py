"""Typed contracts for the functions the host can actually perform.

`mu.py` ranks names; `codex.aiml` suggests them; this module says what a name *means*: parameter
types, an output type, an authority, and - only when it is really implemented - a handler. The
planner composes these and nothing else, so a name that is not registered here can be suggested but
never admitted, and a registered name without a handler can be proposed but never run.

Authorities:
    read           reads the workspace, cannot change it
    write          needs the /allow grant; the sandbox refuses without it anyway
    proposal_only  declared for future plans; no handler, so admission stops at the contract
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

MAX_RESULTS = 50
MAX_READ = 200_000


@dataclass(frozen=True)
class Function:
    name: str
    summary: str
    inputs: tuple[tuple[str, str], ...]
    output: str
    authority: str = "read"
    handler: Callable[..., object] | None = None
    defaults: frozenset[str] = field(default_factory=frozenset)

    def signature(self) -> str:
        """The call form, which is exactly what a completion is allowed to emit."""
        return f"{self.name}({', '.join(param for param, _ in self.inputs)})"

    def contract(self) -> str:
        inputs = ", ".join(f"{param}: {kind}" for param, kind in self.inputs)
        state = "implemented" if self.handler is not None else "no handler"
        return f"{self.name}({inputs}) -> {self.output}  [{self.authority}, {state}]  {self.summary}"


REGISTRY: dict[str, Function] = {}


def register(name: str, summary: str, inputs: tuple[tuple[str, str], ...], output: str,
             *, authority: str = "read", handler: Callable[..., object] | None = None,
             defaults: tuple[str, ...] = ()) -> Function:
    entry = Function(name, summary, tuple(inputs), output, authority, handler, frozenset(defaults))
    REGISTRY[name] = entry
    return entry


def get(name: str) -> Function | None:
    return REGISTRY.get(name)


def declarations() -> tuple[str, ...]:
    """Call forms, in registry order: the candidate pool for completion and for plan validation."""
    return tuple(entry.signature() for entry in REGISTRY.values())


def describe() -> str:
    lines = ["Registered functions:"]
    for entry in REGISTRY.values():
        lines.append(f"  {entry.contract()}")
    lines.append("")
    lines.append("Only an implemented function can appear in a plan that is admitted to run.")
    return "\n".join(lines)


def compatible(given: str, wanted: str) -> bool:
    """One type flows into the next: same name, or either side is deliberately loose."""
    return given == wanted or "any" in {given, wanted}


@dataclass
class ToolContext:
    """Where a handler runs: a workspace root, plus the host sandbox when there is one."""
    root: Path
    tool: object | None = None


def _contained(root: Path, path: str) -> Path:
    target = (Path(root) / str(path or ".").replace("\\", "/")).resolve()
    if not target.is_relative_to(Path(root).resolve()):
        raise ValueError(f"{path!r} escapes the workspace")
    return target


def _list_dir(ctx: ToolContext, path: str = ".") -> list[str]:
    if ctx.tool is not None:
        return ctx.tool.list_dir(path)
    target = _contained(ctx.root, path)
    children = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    return [f"{'[DIR]' if child.is_dir() else '[FILE]'} {child.name}" for child in children[:MAX_RESULTS]]


def _read_file(ctx: ToolContext, path: str) -> str:
    if ctx.tool is not None:
        return ctx.tool.read_file(path)
    return _contained(ctx.root, path).read_text(encoding="utf-8", errors="replace")[:4000]


def _run_command(ctx: ToolContext, program: str, args: list[str] | str) -> str:
    if ctx.tool is None:
        raise RuntimeError("no sandbox attached, so commands are unavailable")
    return ctx.tool.run_command(program, list(args) if not isinstance(args, str) else args.split())


def _git_command(ctx: ToolContext, command: str, arguments: list[str] | None = None) -> str:
    return _run_command(ctx, "git", [str(command), *[str(item) for item in (arguments or [])]])


def _write_file(ctx: ToolContext, path: str, content: str) -> str:
    if ctx.tool is None:
        raise RuntimeError("no sandbox attached, so writes are unavailable")
    return ctx.tool.write_file(path, content)


def _patch_file(ctx: ToolContext, path: str, find: str, replace: str = "") -> str:
    if ctx.tool is None:
        raise RuntimeError("no sandbox attached, so patches are unavailable")
    return ctx.tool.patch_file(path, find, replace)


def _search(ctx: ToolContext, pattern: str, path: str = ".", glob: str = "*.aiml") -> list[dict]:
    """Files whose text contains `pattern`. Paths are workspace-relative, bounded, sorted."""
    root = Path(ctx.root).resolve()
    base = _contained(root, path)
    hits: list[dict] = []
    for file in sorted(base.rglob(glob)):
        if not file.is_file() or file.stat().st_size > MAX_READ:
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if pattern.lower() in text.lower():
            hits.append({"path": file.relative_to(root).as_posix(), "bytes": len(text)})
        if len(hits) >= MAX_RESULTS:
            break
    return hits


def _category_text(file: str, block: str) -> dict | None:
    pattern = re.search(r"<pattern>(.*?)</pattern>", block, re.S | re.I)
    template = re.search(r"<template>(.*?)</template>", block, re.S | re.I)
    if not pattern or not template:
        return None
    return {
        "file": file,
        "pattern": " ".join(pattern.group(1).split()),
        "template": " ".join(template.group(1).split()),
    }


def _parse_aiml(ctx: ToolContext, files: list[dict]) -> list[dict]:
    """Every <category> in those files, with its pattern and template."""
    categories = []
    for row in files or []:
        text = _read_file(ctx, row["path"])
        for block in re.findall(r"<category>(.*?)</category>", text, re.S | re.I):
            entry = _category_text(row["path"], block)
            if entry:
                categories.append(entry)
    return categories


def _filter_categories(ctx: ToolContext, categories: list[dict], needle: str = "") -> list[dict]:
    needle = (needle or "").strip().lower()
    if not needle:
        return list(categories or [])
    return [
        entry for entry in categories or []
        if needle in f"{entry['pattern']} {entry['template']}".lower()
    ]


def _rank_by_context(ctx: ToolContext, categories: list[dict], context: str = "") -> list[dict]:
    words = {word for word in re.findall(r"[a-z0-9_]+", (context or "").lower()) if len(word) > 2}
    scored = []
    for entry in categories or []:
        haystack = f"{entry['pattern']} {entry['template']}".lower()
        score = sum(haystack.count(word) for word in words) or 1
        scored.append({**entry, "score": score})
    scored.sort(key=lambda entry: (-entry["score"], entry["pattern"]))
    return scored


def _fold_lines(ctx: ToolContext, items: list[dict], title: str = "result") -> str:
    if not items:
        return f"{title}\n  (nothing matched)"
    lines = [str(title)]
    for entry in items[:12]:
        label = (entry.get("pattern") or entry.get("file") or entry.get("item") or str(entry)[:60])
        detail = (entry.get("template") or entry.get("state") or entry.get("detail") or "")
        lines.append(f"  {label}  →  {str(detail)[:80]}")
    if len(items) > 12:
        lines.append(f"  … {len(items) - 12} more")
    return "\n".join(lines)


# -- the GML side: whatever the K'UHUL base currently declares -------------------------------------
def _gml_attr(doc, name: str) -> str:
    for entry in getattr(doc, "entries", []) or []:
        if getattr(entry, "name", "") == name:
            return str(entry.value)
    return ""


def _gml_registry(ctx: ToolContext) -> str:
    """The tensor extension as declared right now, read from its GML document."""
    import phases
    return phases.extension_summary()


def _gml_validate(ctx: ToolContext, files: list[dict]) -> list[dict]:
    """Validate GML documents against the base's own registry; foreign schemas are out of scope."""
    import phases
    contract = phases.extension_contract()
    schema_id = contract.get("schema_id") or "gml-tensor/1"
    try:
        gml2 = phases.core_module("gml2")
        registry = phases.core_module("registry")
        loaded = registry.load_registry()
    except Exception as error:
        return [{"file": "-", "state": "UNAVAILABLE", "detail": str(error)[:120]}]
    rows = []
    for row in files or []:
        path = row.get("path") if isinstance(row, dict) else str(row)
        try:
            text = (Path(ctx.root) / path).read_text(encoding="utf-8", errors="replace")
            doc = gml2.parse(text)
            declared = _gml_attr(doc, "schema")
            if declared != schema_id:
                rows.append({"file": path, "state": "OUT_OF_SCOPE", "detail": f"declares {declared or '(none)'}"})
                continue
            registry.validate_document(doc, loaded)
            rows.append({"file": path, "state": "STRUCTURALLY_VALIDATED", "detail": "registry ok"})
        except Exception as error:
            rows.append({"file": path, "state": "REJECTED", "detail": str(error)[:120]})
    return rows


def _gml_assemble(ctx: ToolContext, graph_id: str = "") -> str:
    """A plan-only assembly over the package's own contracts, skipping other extensions' documents."""
    import phases
    try:
        gml2 = phases.core_module("gml2")
        assemble = phases.core_module("assemble")
    except Exception as error:
        return f"the assembler is unavailable: {error}"
    schema_id = phases.extension_contract().get("schema_id") or "gml-tensor/1"
    docs = {}
    for path in sorted((phases.ROOT / "contracts").glob("*.gml")):
        try:
            doc = gml2.parse(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if _gml_attr(doc, "schema") != schema_id:
            continue
        identity = assemble.graph_identity(doc) if hasattr(assemble, "graph_identity") else _gml_attr(doc, "graph_id")
        docs[identity] = doc
    target = docs.get(graph_id or "tensor/assembled") or next(iter(docs.values()), None)
    if target is None:
        return "no tensor document to assemble"
    plan, _ = assemble.assemble(target, docs)
    return (f"{plan.graph_id}: shape={plan.shape} dtype={plan.dtype} "
            f"coverage={plan.coverage}/{plan.total} (plan only, nothing materialized)")


# -- the registry itself ---------------------------------------------------------------------------
register("list_dir", "names in a workspace directory", (("path", "path"),), "entries",
         handler=_list_dir, defaults=("path",))
register("read_file", "text of one workspace file", (("path", "path"),), "text",
         handler=_read_file)
register("search", "files whose text contains a pattern", (("pattern", "pattern"), ("path", "path"), ("glob", "glob")),
         "files", handler=_search, defaults=("path", "glob"))
register("parse_aiml", "the <category> entries in some AIML files", (("files", "files"),), "categories",
         handler=_parse_aiml)
register("filter_categories", "categories whose pattern or template mentions a needle",
         (("categories", "categories"), ("needle", "pattern")), "categories",
         handler=_filter_categories, defaults=("needle",))
register("rank_by_context", "categories ordered by overlap with a context",
         (("categories", "categories"), ("context", "text")), "ranked",
         handler=_rank_by_context, defaults=("context",))
register("fold_lines", "the ranked rows as a readable block",
         (("items", "any"), ("title", "text")), "text",
         handler=_fold_lines, defaults=("title",))
register("gml_registry", "what the GML tensor extension declares right now", (), "text",
         handler=_gml_registry)
register("gml_validate", "validate GML documents against the tensor registry",
         (("files", "files"),), "reports", handler=_gml_validate)
register("gml_assemble", "plan-only tensor assembly over the package's contracts",
         (("graph_id", "text"),), "text", handler=_gml_assemble, defaults=("graph_id",))
register("run_command", "an allowlisted program with allowlisted subcommands",
         (("program", "text"), ("args", "any")), "text", handler=_run_command)
register("git_command", "a read-only git subcommand in the workspace",
         (("command", "text"), ("arguments", "any")), "text", handler=_git_command,
         defaults=("arguments",))
register("write_file", "create or replace a workspace file", (("path", "path"), ("content", "text")), "text",
         authority="write", handler=_write_file)
register("patch_file", "replace one exact span in a workspace file",
         (("path", "path"), ("find", "text"), ("replace", "text")), "text",
         authority="write", handler=_patch_file, defaults=("replace",))

# Declared, deliberately unimplemented: they exist so a plan that needs them is refused at admission
# rather than at the end of a half-run composition.
register("search_history", "messages from earlier sessions", (("query", "text"),), "text",
         authority="proposal_only", handler=None, defaults=("query",))
register("update_task_list", "mutate task-list.json through the bus",
         (("action", "text"), ("task", "text")), "text", authority="proposal_only", handler=None,
         defaults=("task",))
register("fetch_weather", "current conditions for a place", (("city", "text"),), "weather",
         authority="proposal_only", handler=None)
register("translate_text", "translate text into a language", (("text", "text"), ("language", "text")), "text",
         authority="proposal_only", handler=None)
