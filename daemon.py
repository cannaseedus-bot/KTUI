"""AIML/SRAI daemon bot engine: the six-phase cycle, and the mode bias vectors behind it.

Two things in the K'UHUL package are usable by this host as they stand:

  integrations/daemon-modes.aiml   58 response modes, each carrying a bias vector
                                   (empathy, reasoning, initiative, skepticism, creativity)
  registry/phase-contract.json     the cycle Pop -> Wo -> Yax -> Sek -> Ch'en -> Xul

So every turn runs through the cycle and records what each phase actually did. The engine
*proposes*; it admits through the gates that already exist - the sandbox allowlist here, and the
planner for compositions - and it never executes on its own authority. A fuzzy candidate from the
vector map may only ever select a read-only directive; anything else is deferred to the model.

The mode vector is a style prior for the model's system prompt. AIML itself has no notion of a
bias, so the kernel is not told one; that would be theatre.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import phases

APP_ROOT = Path(__file__).resolve().parent
MODE_FILE = phases.ROOT / "integrations" / "daemon-modes.aiml"
BIAS_FIELDS = ("empathy", "reasoning", "initiative", "skepticism", "creativity")
THRESHOLD = 0.34

BEHAVIOR = re.compile(r'xaiml:behavior\s+mode="([^"]+)"[^>]*priority="([^"]*)"', re.I)
BIAS = re.compile(r"xaiml:bias\s+([^/]*)/>", re.I)
ATTRIBUTE = re.compile(r'(\w+)="([^"]*)"')
CATEGORY = re.compile(r"<category>(.*?)</category>", re.S | re.I)
PATTERN = re.compile(r"<pattern>(.*?)</pattern>", re.S | re.I)
TEMPLATE = re.compile(r"<template>(.*?)</template>", re.S | re.I)
MODE_TAG = re.compile(r'xaiml:behavior\s+mode="([^"]+)"', re.I)
SRAI = re.compile(r"<srai>(.*?)</srai>", re.S | re.I)
TOKEN = re.compile(r"[a-z0-9_]+")
STOPWORDS = frozenset("a an the of to in is are was were do does what which how me my i you it that this for on with and or".split())
MODE_MARK = "mode:"

# Only these verbs may be chosen by similarity: reads and pure computation. Never a write.
READ_VERBS = frozenset({"git", "time", "files", "convert"})


@dataclass(frozen=True)
class Mode:
    name: str
    priority: str
    bias: dict[str, float]

    def vector(self) -> str:
        return " · ".join(f"{field} {self.bias.get(field, 0.0):.2f}" for field in BIAS_FIELDS)

    def prompt(self) -> str:
        """One line the model can act on, instead of five bare numbers."""
        return (
            f"style prior from mode '{self.name}': "
            + ", ".join(f"{field} {self.bias.get(field, 0.0):.2f}" for field in BIAS_FIELDS)
            + " (0..1; higher means more of it)"
        )


def modes(path: Path = MODE_FILE) -> dict[str, Mode]:
    """Mode definitions as declared in the AIML bank, in file order, first declaration wins.

    Pairing is per `<category>`: a file can carry more behaviour tags than bias tags (a mode
    declared primary and secondary), so zipping two flat lists by index would drift.
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    found: dict[str, Mode] = {}
    for block in CATEGORY.findall(text):
        behavior = MODE_TAG.search(block)
        if not behavior:
            continue
        name = behavior.group(1)
        if name in found:
            continue
        bias_block = BIAS.search(block)
        raw = dict(ATTRIBUTE.findall(bias_block.group(1))) if bias_block else {}
        bias = {field: float(raw.get(field, 0.0)) for field in BIAS_FIELDS}
        priority_match = re.search(r'priority="([^"]*)"', block)
        found[name] = Mode(name=name, priority=priority_match.group(1) if priority_match else "", bias=bias)
    return found


def describe_modes(path: Path = MODE_FILE) -> str:
    table = modes(path)
    if not table:
        return "No daemon modes found (integrations/daemon-modes.aiml)."
    lines = [f"{len(table)} daemon modes, with the bias vector each one carries:", ""]
    for mode in list(table.values())[:8]:
        lines.append(f"  {mode.name:<14} {mode.vector()}")
    lines.append("  …")
    lines.append("")
    lines.append("all: " + ", ".join(table))
    lines.append("")
    lines.append("`/mode <name>` switches; the vector becomes the model's style prior, and `/mode` alone lists.")
    return "\n".join(lines)


def _tokens(text: str) -> list[str]:
    return [token for token in TOKEN.findall(text.lower()) if token not in STOPWORDS]


class VectorMap:
    """A tiny TF map over AIML patterns, so a near-miss can still be found deterministically.

    No embeddings, no model, no network: term frequencies and cosine similarity. That is enough to
    say "this input is closest to WHAT CHANGED", which the literal matcher cannot say at all.
    """

    def __init__(self, banks: Sequence[Path]) -> None:
        self.vectors: list[tuple[str, Counter, str]] = []
        for path in banks:
            for pattern, template in self._categories(Path(path)):
                tokens = _tokens(pattern)
                if not tokens:
                    continue
                self.vectors.append((pattern, Counter(tokens), template))

    @staticmethod
    def _categories(path: Path) -> list[tuple[str, str]]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        found = []
        for block in CATEGORY.findall(text):
            pattern = PATTERN.search(block)
            template = TEMPLATE.search(block)
            if pattern and template:
                found.append((" ".join(pattern.group(1).split()), " ".join(template.group(1).split())))
        return found

    def similar(self, text: str, limit: int = 5) -> list[tuple[float, str, str]]:
        query = Counter(_tokens(text))
        if not query:
            return []
        scored = []
        for pattern, vector, template in self.vectors:
            score = self._cosine(query, vector)
            if score > 0:
                scored.append((score, pattern, template))
        scored.sort(key=lambda row: -row[0])
        return scored[:max(1, limit)]

    @staticmethod
    def _cosine(left: Counter, right: Counter) -> float:
        shared = set(left) & set(right)
        if not shared:
            return 0.0
        numerator = sum(left[token] * right[token] for token in shared)
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


@dataclass
class Turn:
    """One traversal of the cycle, with what each phase saw and decided."""
    text: str
    kind: str = "deferred"
    answer: str = ""
    mode: str = ""
    phases: list[tuple[str, str]] = field(default_factory=list)

    def trace(self) -> str:
        width = max((len(name) for name, _ in self.phases), default=4)
        lines = [f"turn: {self.text!r} → {self.kind}" + (f" · mode {self.mode}" if self.mode else "")]
        for name, detail in self.phases:
            lines.append(f"  {name:<{width}}  {detail}")
        return "\n".join(lines)


class Daemon:
    """Drives one turn through Pop → Wo → Yax → Sek → Ch'en → Xul.

    The host supplies the kernel reply and the two gates, so this class owns the *order and the
    record*, not the authority: `kernel(text)` for AIML, `admit(verb, argument)` for tool verbs and
    `admit_plan(name)` for compositions.
    """

    def __init__(self, *, kernel: Callable[[str], str], banks: Sequence[Path],
                 admit: Callable[[str, str], tuple[bool, str]],
                 admit_plan: Callable[[str], tuple[bool, str]],
                 admit_memory: Callable[[str, str], tuple[bool, str]] | None = None,
                 mode_of: Callable[[], str] = lambda: "") -> None:
        self.kernel = kernel
        self.admit = admit
        self.admit_plan = admit_plan
        # Memory operations are proposals like everything else: memquery is read-only, a write needs
        # an explicit grant. Without a host callback nothing is admitted.
        self.admit_memory = admit_memory or (lambda kind, argument: (False, "memory is unavailable"))
        self.mode_of = mode_of
        self.map = VectorMap(banks)
        self.phases = phases.phase_order() or ("Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul")

    # -- the phases -----------------------------------------------------------------------------
    def _follow(self, template: str) -> str:
        """A matched category may redirect (`<srai>`); the directive is at the end of that hop."""
        hop = SRAI.search(template)
        if not hop:
            return template
        target = " ".join(hop.group(1).split())
        try:
            return " ".join(str(self.kernel(target.upper()) or "").split())
        except Exception:
            return ""

    def run(self, text: str) -> Turn:
        turn = Turn(text=text)
        record = lambda name, detail: turn.phases.append((name, detail))  # noqa: E731

        # Pop: ingress. Bounded, normalised, and the only place the vector map is consulted.
        text = " ".join(str(text or "").split())[:500]
        candidates = self.map.similar(text, limit=5)
        best = candidates[0] if candidates else (0.0, "", "")
        record("Pop", f"{len(_tokens(text))} token(s) · {len(candidates)} candidate(s) · best {best[0]:.2f} {best[1] or '-'}")

        # Wo: field binding. The literal matcher is the authority; its reply is kept verbatim.
        reply = ""
        try:
            reply = " ".join(str(self.kernel(text.upper()) or "").split())
        except Exception as error:
            record("Wo", f"kernel error: {error}")
        else:
            record("Wo", f"kernel: {reply[:60]!r}" if reply else "kernel: no match")
        mode_tag = MODE_TAG.search(reply)
        if mode_tag:
            turn.kind, turn.mode = "mode", mode_tag.group(1)
            record("Yax", f"mode declaration in bank: {turn.mode}")
            record("Sek", "proposal: switch response mode")
            record("Ch'en", "admitted: a mode is style, not I/O")
            record("Xul", f"closed: mode {turn.mode}")
            return turn

        # Yax: candidate traversal. A literal directive wins; otherwise walk the vector candidates
        # in order and take the first that is admissible: a mode declaration, or a directive whose
        # template has no unsubstituted markup left in it.
        selected, source = "", ""
        if reply and "__LLM_FALLBACK__" not in reply and not reply.startswith(("CODEX_SUGGEST ", "CODEX_LOOKUP ")):
            selected, source = reply, "literal"
        else:
            for score, pattern, template in candidates:
                if score < THRESHOLD:
                    break
                tag = MODE_TAG.search(template)
                if tag:
                    selected, source = f"{MODE_MARK}{tag.group(1)}", f"vector {score:.2f} via {pattern}"
                    break
                resolved = self._follow(template)
                if (resolved.upper().startswith(("TOOL ", "CODEX_PLAN "))
                        and "<" not in resolved and "&" not in resolved):
                    selected, source = resolved, f"vector {score:.2f} via {pattern}"
                    break
        record("Yax", f"{source or 'nothing'} → {selected[:60]!r}" if selected else "nothing above threshold")

        if not selected:
            record("Sek", "no proposal")
            record("Ch'en", "nothing to admit")
            record("Xul", "deferred to the model")
            return turn

        # Sek: proposal only. Nothing is executed in this phase.
        if selected.startswith(MODE_MARK):
            proposal = ("mode", selected[len(MODE_MARK):].strip(), "")
        elif selected.upper().startswith("TOOL "):
            verb, _, argument = selected[5:].partition(" ")
            proposal = ("tool", verb.strip().lower(), argument.strip())
        elif selected.strip().upper() == "IDENTITY":
            proposal = ("identity", "", "")
        elif selected.upper().startswith("MEMORY "):
            proposal = ("memory", selected[len("MEMORY "):].strip(), "")
        elif selected.upper().startswith("MEMQUERY "):
            proposal = ("memquery", selected[len("MEMQUERY "):].strip(), "")
        elif selected.upper().startswith("CODEX_PLAN "):
            payload = selected[len("CODEX_PLAN "):].strip()
            # The bank writes `CODEX_PLAN proposal <name> <term>`; the verb is the bank's, not a name.
            for verb in ("proposal ", "run "):
                if payload.lower().startswith(verb):
                    payload = payload[len(verb):].strip()
                    break
            proposal = ("plan", payload, "")
        else:
            proposal = ("aiml", selected, "")
        record("Sek", f"proposal: {proposal[0]} {proposal[1][:50]} (from {source})")

        # Ch'en: verification and admission, through the host's existing gates.
        kind, payload, argument = proposal
        if kind == "mode":
            record("Ch'en", "admitted: a mode is style, not I/O")
            turn.kind, turn.mode = "mode", payload
            record("Xul", f"closed: mode {payload}")
            return turn
        if kind == "tool" and payload not in READ_VERBS:
            record("Ch'en", f"refused: {payload} may not be selected by similarity")
            record("Xul", "deferred to the model")
            return turn
        if kind == "tool":
            admitted, why = self.admit(payload, argument)
        elif kind == "plan":
            admitted, why = self.admit_plan(payload)
        elif kind in {"memory", "memquery"}:
            admitted, why = self.admit_memory(kind, payload)
        elif kind == "identity":
            admitted, why = True, "local identity text, rendered by the host"
        else:
            admitted, why = True, "plain AIML answer"
        record("Ch'en", ("admitted: " if admitted else "refused: ") + why)
        if not admitted:
            record("Xul", "deferred to the model")
            return turn

        # Xul: closure. The kind is what the host renders; the text is what it renders.
        turn.kind, turn.answer = kind, payload if kind != "tool" else f"{payload} {argument}".strip()
        record("Xul", f"closed: {kind}")
        return turn
