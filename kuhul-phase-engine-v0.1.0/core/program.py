"""K'UHUL program layer: parse, validate, serialize and trace a program - never execute it.

The grammar (declaration / instruction / phase-block / lane-block / binding, with `⟁glyph`
references) describes *what* a program means structurally. Nothing here runs a tool, writes a file or
grants authority: `evaluate()` produces a trace with each step's resolved arguments and its declared
effect. A step whose implementation is not bound says so instead of pretending it ran.

Two dialects are accepted because the package ships both:

    call style   glyph ⟁DATA = "…"  ·  map(⟁DATA)  ·  Pop { … }  ·  lane risk : Graph { … }
    bracket style [Pop enterprise_shipping_impact]  ·  [Yax resolve "risk_shipping"]  ·  [Xul]

The bracket reader exists so `graphs/shipping-impact.khl` parses; it maps onto the same AST.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OPCODES = ("map", "filter", "fold", "reduce", "sync", "emit", "verify", "dispatch")
PHASES = ("Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul")
PHASE_ALIASES = {"Chen": "Ch'en", "Ch'en": "Ch'en", "Sek": "Sek", "Pop": "Pop", "Wo": "Wo",
                 "Yax": "Yax", "Xul": "Xul"}
TYPES = ("Glyph", "Vector", "Field", "Tensor", "Graph", "Scalar", "Memory", "Program")
KHL_OPS = ("enter", "bind", "resolve", "traverse", "filter", "map", "fold", "accumulate",
           "reduce", "verify", "emit", "dispatch")
ARITY = {"map": (1, 2), "filter": (1, 2), "fold": (1, 3), "reduce": (1, 2), "sync": (1, 3),
         "emit": (1, 2), "verify": (1, 2), "dispatch": (1, 2)}
GLYPH = "⟁"
EFFECT = {"map": "transforms a lane", "filter": "narrows a lane", "fold": "accumulates a lane",
          "reduce": "collapses a lane to a scalar", "sync": "merges lanes", "emit": "appends output",
          "verify": "checks assertions", "dispatch": "selects a target"}


PHASE_BY_LOWER = {"pop": "Pop", "wo": "Wo", "yax": "Yax", "sek": "Sek",
                  "chen": "Ch'en", "ch'en": "Ch'en", "xul": "Xul"}


def phase_of(word: str) -> str | None:
    """Accept the grammar's `Chen` and the corpus' `Ch'en`; canonicalize to `Ch'en`."""
    return PHASE_BY_LOWER.get(str(word or "").strip().lower())

class ProgramError(ValueError):
    """A program that does not parse, or does not satisfy the grammar's own rules."""


# -- lexer ------------------------------------------------------------------------------------------
TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<comment>\#[^\n]*)
  | (?P<arrow>->)
  | (?P<glyph>⟁[A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z][A-Za-z0-9_]*)*)
  | (?P<string>"(?:[^"\\\n]|\\.)*")
  | (?P<number>\d+)
  | (?P<ident>[A-Za-z][A-Za-z0-9_']*)
  | (?P<punct>[(){},:=])
""", re.VERBOSE)


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    offset: int


def tokenize(text: str) -> list[Token]:
    tokens, position = [], 0
    while position < len(text):
        match = TOKEN.match(text, position)
        if match is None:
            raise ProgramError(f"unexpected character {text[position]!r} at {position}")
        position = match.end()
        kind = match.lastgroup
        if kind in ("space", "comment"):
            continue
        tokens.append(Token(kind, match.group(), match.start()))
    return tokens


# -- AST --------------------------------------------------------------------------------------------
@dataclass
class Value:
    kind: str            # glyph | ident | number | string
    value: str | int

    def text(self) -> str:
        if self.kind == "string":
            return '"' + self.value.replace("\\", "\\\\").replace('"', '\\"') + '"'
        if self.kind == "glyph":
            return f"{GLYPH}{self.value}"
        return str(self.value)


@dataclass
class Declaration:
    name: str
    value: str
    relation: bool = False

    def text(self) -> str:
        keyword = "relation" if self.relation else "glyph"
        return f'{keyword} {self.name} = "{self.value}"'


@dataclass
class Instruction:
    opcode: str
    args: list[Value] = field(default_factory=list)

    def text(self) -> str:
        return f"{self.opcode}(" + ", ".join(arg.text() for arg in self.args) + ")"


@dataclass
class PhaseBlock:
    phase: str
    body: list = field(default_factory=list)


@dataclass
class LaneBlock:
    name: str
    type: str
    body: list = field(default_factory=list)


@dataclass
class Binding:
    source: Value
    target: Value


Statement = object | Declaration | Instruction | PhaseBlock | LaneBlock | Binding


@dataclass
class Program:
    statements: list = field(default_factory=list)

    # -- convenience ---------------------------------------------------------------------------
    def walk(self):
        """Every statement, depth first, phases and lanes included."""
        for statement in self.statements:
            yield statement
            if isinstance(statement, (PhaseBlock, LaneBlock)):
                inner = Program(statement.body)
                yield from inner.walk()

    def opcodes(self) -> list[str]:
        return [item.opcode for item in self.walk() if isinstance(item, Instruction)]

    def glyphs(self) -> dict:
        return {item.name: item.value for item in self.walk()
                if isinstance(item, Declaration) and not item.relation}

    def relations(self) -> dict:
        return {item.name: item.value for item in self.walk()
                if isinstance(item, Declaration) and item.relation}

    def lanes(self) -> dict:
        return {item.name: item.type for item in self.walk() if isinstance(item, LaneBlock)}

    def phase_order(self) -> list[str]:
        seen = []
        for item in self.walk():
            if isinstance(item, PhaseBlock) and item.phase not in seen:
                seen.append(item.phase)
        return seen


# -- parser (call style) -----------------------------------------------------------------------------
class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0

    def peek(self, offset: int = 0) -> Token | None:
        position = self.index + offset
        return self.tokens[position] if position < len(self.tokens) else None

    def take(self, kind: str | None = None, value: str | None = None) -> Token:
        token = self.peek()
        if token is None:
            raise ProgramError("unexpected end of program")
        if kind is not None and token.kind != kind:
            raise ProgramError(f"expected {kind} at {token.offset}, got {token.value!r}")
        if value is not None and token.value.lower() != value:
            raise ProgramError(f"expected {value!r} at {token.offset}, got {token.value!r}")
        self.index += 1
        return token

    def program(self) -> Program:
        statements = []
        while self.peek() is not None:
            statements.append(self.statement())
        return Program(statements)

    def statement(self):
        token = self.peek()
        if token is None:
            raise ProgramError("unexpected end of program")
        word = token.value.lower()
        if token.kind == "ident" and word in ("glyph", "relation"):
            return self.declaration()
        if token.kind == "ident" and phase_of(word):
            return self.phase_block()
        if token.kind == "ident" and self.peek(1) is not None and self.peek(1).value == "{":
            raise ProgramError(f"not a phase: {token.value!r} (expected one of {', '.join(PHASES)})")
        if token.kind == "ident" and word == "lane":
            return self.lane_block()
        if token.kind == "ident" and word == "bind":
            return self.binding()
        if token.kind == "ident":
            return self.instruction()
        raise ProgramError(f"unexpected token {token.value!r} at {token.offset}")

    def declaration(self) -> Declaration:
        keyword = self.take("ident").value.lower()
        name = self.take("ident").value
        self.take("punct", "=")
        value = self.take("string").value
        return Declaration(name=name, value=value[1:-1], relation=(keyword == "relation"))

    def phase_block(self) -> PhaseBlock:
        raw = self.take("ident").value
        phase = phase_of(raw)
        if phase is None:
            raise ProgramError(f"not a phase: {raw!r}")
        self.take("punct", "{")
        body = []
        while self.peek() is not None and self.peek().value != "}":
            body.append(self.statement())
        self.take("punct", "}")
        return PhaseBlock(phase=phase or raw, body=body)

    def lane_block(self) -> LaneBlock:
        self.take("ident", "lane")
        name = self.take("ident").value
        self.take("punct", ":")
        lane_type = self.take("ident").value
        self.take("punct", "{")
        body = []
        while self.peek() is not None and self.peek().value != "}":
            body.append(self.statement())
        self.take("punct", "}")
        return LaneBlock(name=name, type=lane_type, body=body)

    def binding(self) -> Binding:
        self.take("ident", "bind")
        source = self.value()
        self.take("arrow")
        target = self.value()
        return Binding(source=source, target=target)

    def instruction(self) -> Instruction:
        token = self.take("ident")
        opcode = token.value.lower()
        self.take("punct", "(")
        args = []
        if self.peek() is not None and self.peek().value != ")":
            args.append(self.value())
            while self.peek() is not None and self.peek().value == ",":
                self.take("punct", ",")
                args.append(self.value())
        self.take("punct", ")")
        return Instruction(opcode=opcode, args=args)

    def value(self) -> Value:
        token = self.peek()
        if token is None:
            raise ProgramError("expected a value at end of program")
        if token.kind == "glyph":
            self.take()
            return Value("glyph", token.value[len(GLYPH):])
        if token.kind == "string":
            self.take()
            return Value("string", token.value[1:-1])
        if token.kind == "number":
            self.take()
            return Value("number", int(token.value))
        if token.kind == "ident":
            self.take()
            return Value("ident", token.value)
        raise ProgramError(f"expected a value at {token.offset}, got {token.value!r}")


def parse(text: str) -> Program:
    return Parser(tokenize(text)).program()


# -- parser (bracket style, as shipped in graphs/*.khl) -----------------------------------------------
BRACKET = re.compile(r"\[([^\]]*)\]")


def parse_khl(text: str) -> Program:
    """`[Pop name]  [Wo key = "value"]  [Yax resolve "x"]  [Sek FILTER "y"]` -> the same AST.

    The bracket dialect groups statements by phase. Repeating a phase (`[Wo graph = …]`,
    `[Wo scenario = …]`) appends to the block that phase already opened, so the six phases stay six
    blocks rather than becoming one block per line.
    """
    blocks: dict[str, PhaseBlock] = {}
    order: list[PhaseBlock] = []
    for match in BRACKET.finditer(text):
        body = match.group(1).strip()
        if not body:
            continue
        head, _, rest = body.partition(" ")
        head, rest = head.strip(), rest.strip()
        phase = phase_of(head)
        if phase is not None:
            block = blocks.get(phase)
            if block is None:
                block = blocks[phase] = PhaseBlock(phase=phase, body=[])
                order.append(block)
            rest = rest.strip()
            if not rest:
                continue
            word, _, tail = rest.partition(" ")
            if "=" in word or "=" in rest:
                key, _, value = rest.partition("=")
                block.body.append(Declaration(name=key.strip(), value=value.strip().strip('"')))
            elif word.lower() in KHL_OPS:
                block.body.append(Instruction(opcode=word.lower(),
                                              args=[Value("string", tail.strip().strip('"'))]))
            else:
                block.body.append(Declaration(name="phase_name", value=rest.strip('"')))
            continue
        block = order[-1] if order else blocks.setdefault(
            "Pop", PhaseBlock(phase="Pop", body=[]))
        if not order:
            order.append(block)
        word, _, tail = body.partition(" ")
        if word.lower() in KHL_OPS:
            block.body.append(Instruction(opcode=word.lower(),
                                          args=[Value("string", tail.strip().strip('"'))]
                                          if tail.strip() else []))
        else:
            block.body.append(Declaration(name=word, value=tail.strip().strip('"')))
    return Program(statements=list(order))


# -- validation -------------------------------------------------------------------------------------
def validate(program: Program, *, dialect: str = "call",
             strict_order: bool = False) -> dict:
    """Grammar rules the parser cannot check: vocabularies, arity, references, bindings."""
    problems: list[dict] = []
    opcodes = set(OPCODES) if dialect == "call" else set(KHL_OPS)
    glyphs = program.glyphs()
    relations = program.relations()
    lanes = program.lanes()
    known = set(glyphs) | set(relations) | set(lanes)

    for item in program.walk():
        if isinstance(item, Instruction):
            if item.opcode not in opcodes:
                problems.append(dict(code="unknown_opcode", detail=item.opcode,
                                     where=EFFECT.get(item.opcode, "?")))
                continue
            if dialect == "call":
                low, high = ARITY[item.opcode]
                if not low <= len(item.args) <= high:
                    problems.append(dict(code="arity",
                                         detail=f"{item.opcode} takes {low}..{high} arguments, "
                                                f"got {len(item.args)}"))
            for argument in item.args:
                if argument.kind == "glyph" and argument.value not in known:
                    problems.append(dict(code="unresolved_glyph", detail=argument.value))
                elif argument.kind == "ident" and argument.value not in set(lanes) | set(PHASES):
                    problems.append(dict(code="unresolved_reference", detail=argument.value))
        elif isinstance(item, LaneBlock):
            if item.type not in TYPES:
                problems.append(dict(code="unknown_lane_type", detail=f"{item.name}: {item.type}"))
        elif isinstance(item, PhaseBlock):
            if item.phase not in PHASES:
                problems.append(dict(code="unknown_phase", detail=item.phase))
        elif isinstance(item, Binding):
            for side in (item.source, item.target):
                if side.kind == "glyph" and side.value not in known:
                    problems.append(dict(code="unresolved_glyph", detail=side.value))
                elif side.kind == "ident" and side.value not in known:
                    problems.append(dict(code="unresolved_binding", detail=side.value))
    # Phases are a vocabulary, not a schedule: which ones a program uses - and in which order - is the
    # program's business, because a phase is meaningful only for the work it does. Only an unknown
    # phase name is a defect. Callers that want the canonical sequence enforced can ask for it.
    used = program.phase_order()
    canonical = [phase for phase in PHASES if phase in used]
    if strict_order and used != canonical:
        problems.append(dict(code="phase_order",
                             detail=f"written {used} but canonical is {canonical}"))
    order = ("canonical" if tuple(used) == PHASES else
             "subset" if used == canonical else "as-written")
    return dict(ok=not problems, problems=problems, opcodes=program.opcodes(),
                phases=used, canonical=canonical, order=order,
                glyphs=len(glyphs), relations=len(relations), lanes=lanes)


# -- serialization -----------------------------------------------------------------------------------
def _serialize_body(body: list, indent: int) -> list[str]:
    pad = "  " * indent
    lines = []
    for item in body:
        if isinstance(item, Declaration):
            lines.append(pad + item.text())
        elif isinstance(item, Instruction):
            lines.append(pad + item.text())
        elif isinstance(item, Binding):
            lines.append(pad + f"bind {item.source.text()} -> {item.target.text()}")
        elif isinstance(item, PhaseBlock):
            lines.append(pad + f"{item.phase} {{")
            lines += _serialize_body(item.body, indent + 1)
            lines.append(pad + "}")
        elif isinstance(item, LaneBlock):
            lines.append(pad + f"lane {item.name} : {item.type} {{")
            lines += _serialize_body(item.body, indent + 1)
            lines.append(pad + "}")
    return lines


def serialize(program: Program) -> str:
    return "\n".join(_serialize_body(program.statements, 0)) + "\n"


# -- tracing (never execution) -------------------------------------------------------------------------
def evaluate(program: Program, *, lanes: dict | None = None, glyphs: dict | None = None,
             implementations: dict | None = None) -> dict:
    """Walk the program in phase order and record what each step would do.

    A step is *bound* when the caller supplies a callable for its opcode; otherwise it is recorded as
    deferred with the reason. Nothing outside this function's own state is touched, so a trace cannot
    execute a tool, write a file, or admit anything.
    """
    lanes = dict(lanes or {})
    glyphs = dict(glyphs or program.glyphs())
    implementations = implementations or {}
    trace = []
    current_phase = "-"
    for item in program.walk():
        if isinstance(item, LaneBlock):
            lanes.setdefault(item.name, [])
            trace.append(dict(phase="lane", step="lane", lane=item.name, type=item.type,
                              effect="declares a lane", bound=True))
            continue
        if isinstance(item, PhaseBlock):
            current_phase = item.phase
            trace.append(dict(phase=item.phase, step="phase", effect="opens a phase", bound=True))
            continue
        if isinstance(item, Declaration):
            continue
        if isinstance(item, Binding):
            trace.append(dict(phase=current_phase, step="bind", source=item.source.text(),
                              target=item.target.text(), effect="binds two names", bound=True))
            continue
        implementation = implementations.get(item.opcode)
        resolved = []
        for argument in item.args:
            if argument.kind == "glyph":
                resolved.append(glyphs.get(argument.value, argument.text()))
            else:
                resolved.append(argument.value)
        entry = dict(phase=current_phase, step=item.opcode, effect=EFFECT.get(item.opcode, "?"),
                     arguments=resolved, bound=implementation is not None)
        if implementation is None:
            entry["deferred"] = "no implementation bound for this opcode"
        else:
            try:
                entry["result"] = implementation(lanes, *resolved)
                entry["bound"] = True
            except Exception as error:  # a failed step is reported, not hidden
                entry["error"] = f"{type(error).__name__}: {error}"
                entry["bound"] = False
        trace.append(entry)
    phases = [entry["phase"] for entry in trace if "phase" in entry]
    return dict(schema="kuhul.program.trace/1", ok=not any("error" in entry for entry in trace),
                steps=len(trace), deferred=sum(1 for entry in trace if entry.get("deferred")),
                phases=[phase for phase in phases if phase != "lane"],
                trace=trace, execution=False, mutation=False, authority="host")


def summary(program: Program, *, dialect: str = "call") -> str:
    report = validate(program, dialect=dialect)
    lines = [f"program: {len(program.statements)} statement(s) · {len(report['opcodes'])} instruction(s)"
             f" · phases {', '.join(report['phases']) or '(none)'}"
             f" · {'valid' if report['ok'] else 'INVALID'}"]
    for problem in report["problems"][:6]:
        lines.append(f"  {problem['code']}: {problem['detail']}")
    return "\n".join(lines)


def load(path: Path) -> tuple[Program, str]:
    """Parse a file, choosing the dialect from the syntax it actually uses."""
    text = Path(path).read_text(encoding="utf-8")
    if BRACKET.search(text) and "(" not in text.split("[")[0]:
        return parse_khl(text), "khl"
    return parse(text), "call"
