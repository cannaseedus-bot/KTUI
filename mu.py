"""KNUMATIC completion micronaut: six-phase, suggestion-only KUHUL pipeline.

No execution, filesystem writes, or implicit authority. Candidates are declarations,
not callable permissions. Integrate with codex.aiml and sandbox registry at the host.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

MODES = frozenset({'code', 'command', 'sentence', 'question', 'path'})

@dataclass(frozen=True)
class Candidate:
    text: str
    source: str
    kind: str = 'function'
    score: float = 0.0
    detail: str = ''

@dataclass
class CompletionContext:
    prefix: str
    cursor: int
    mode: str
    source: str
    workspace: Path
    candidate_functions: tuple[Candidate, ...] = ()
    trace: list[str] = field(default_factory=list)

class Micronaut:
    """Declarative completion selector. Xul closes a result, never dispatches tools."""
    def __init__(self, registry: Mapping[str, Iterable[str]] | None = None):
        self.registry = {k: tuple(v) for k, v in (registry or {}).items()}

    def complete(self, prefix: str, *, cursor: int | None = None,
                 mode: str = 'code', source: str = 'registry',
                 workspace: str | Path = '.', limit: int = 8) -> CompletionContext:
        # Pop: ingress; input is bounded and immutable after capture.
        if not isinstance(prefix, str) or len(prefix) > 8192:
            raise ValueError('prefix must be text of at most 8192 characters')
        ctx = CompletionContext(prefix, len(prefix) if cursor is None else cursor,
                                mode, source, Path(workspace))
        ctx.trace.append('Pop:prefix')
        # Wo: cursor is a character offset, not a terminal cell offset.
        if not 0 <= ctx.cursor <= len(prefix):
            raise ValueError('cursor outside prefix')
        stem = prefix[:ctx.cursor].split()[-1] if prefix[:ctx.cursor].split() else ''
        ctx.trace.append('Wo:cursor')
        # Yax: select mode, without granting execution authority.
        if mode not in MODES:
            raise ValueError(f'unknown completion mode: {mode}')
        ctx.trace.append('Yax:mode')
        # Sek: read declarations from the selected source.
        declarations = self.registry.get(source, ())
        ctx.trace.append('Sek:source')
        # Ch'en: validate workspace scope; do not read files or infer permissions.
        if not str(workspace).strip():
            raise ValueError('workspace is required')
        ctx.workspace = ctx.workspace.expanduser().resolve(strict=False)
        ctx.trace.append("Ch'en:workspace")
        # Xul: deterministic rank, deduplication, and bounded closure.
        seen: set[str] = set()
        candidates: list[Candidate] = []
        for item in declarations:
            if not isinstance(item, str) or not item or item in seen:
                continue
            seen.add(item)
            if stem and stem.lower() not in item.lower():
                continue
            score = 1.0 if item.lower().startswith(stem.lower()) else 0.5
            candidates.append(Candidate(text=item, source=source, kind=mode, score=score))
        candidates.sort(key=lambda c: (-c.score, c.text.casefold()))
        ctx.candidate_functions = tuple(candidates[:max(0, min(limit, 50))])
        ctx.trace.append('Xul:candidate_functions')
        return ctx

if __name__ == '__main__':
    engine = Micronaut({'sandbox': ('read_file(path)', 'write_file(path, content)',
                                    'list_dir(path)', 'run_command(program, args)')})
    result = engine.complete('read_f', source='sandbox')
    for candidate in result.candidate_functions:
        print(candidate.text)
