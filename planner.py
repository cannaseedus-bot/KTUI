"""Plans: linear compositions of registered functions, admitted only when every step is real.

AIML/SRAI may *propose* a plan by name (codex.aiml emits `CODEX_PLAN <name>`), but a name is not
authority. A plan is admitted only when:

  1. every step names a function in `functions.REGISTRY`,
  2. every step has a handler (a declared-but-unimplemented function stops admission),
  3. every step's first input type is the previous step's output type,
  4. every required argument is supplied by the plan or has a default,
  5. its authority is one the runner recognises — and only `execute` actually runs.

`proposal_only` plans can be displayed and inspected; they never run.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import functions

APP_ROOT = Path(__file__).resolve().parent
PLANS_PATH = APP_ROOT / "plans.toml"
AUTHORITIES = {"proposal_only", "execute", "read"}


@dataclass(frozen=True)
class Step:
    function: str
    args: Mapping[str, str] = field(default_factory=dict)


@dataclass
class Plan:
    name: str
    title: str
    authority: str
    steps: tuple[Step, ...]
    problems: tuple[str, ...] = ()

    @property
    def admitted(self) -> bool:
        return not self.problems

    def chain(self) -> str:
        return " → ".join(step.function for step in self.steps)

    def diagram(self) -> str:
        """Each step with the type it returns, and what the previous step handed it."""
        lines = []
        previous: str | None = None
        for index, step in enumerate(self.steps, 1):
            entry = functions.get(step.function)
            if entry is None:
                lines.append(f"  {index}. {step.function}  (not registered)")
                previous = None
                continue
            link = f"   ← {previous}" if previous and index > 1 else ""
            lines.append(f"  {index}. {entry.signature()} → {entry.output}{link}")
            previous = entry.output
        return "\n".join(lines)

    def summary(self) -> str:
        state = "admitted" if self.admitted else f"refused ({len(self.problems)} problem(s))"
        return f"{self.name} · {self.authority} · {state} · {self.chain()}"


def load(path: Path = PLANS_PATH) -> dict[str, Plan]:
    """Every plan in the file, already resolved against the registry."""
    try:
        with Path(path).open("rb") as stream:
            document = tomllib.load(stream)
    except (OSError, ValueError):
        return {}
    specs = document.get("plan") or {}
    return {str(name): resolve(name, spec) for name, spec in specs.items() if isinstance(spec, dict)}


def resolve(name: str, spec: Mapping | None = None, *, plans_path: Path = PLANS_PATH) -> Plan:
    """Validate one plan. With no spec, the name is looked up in plans.toml."""
    if spec is None:
        try:
            with Path(plans_path).open("rb") as stream:
                spec = ((tomllib.load(stream).get("plan") or {}).get(name))
        except (OSError, ValueError):
            spec = None
        if not isinstance(spec, dict):
            return Plan(name, name, "proposal_only", (), (f"{name!r} is not a plan in {plans_path.name}",))

    steps = tuple(
        Step(str((raw or {}).get("function") or ""), dict((raw or {}).get("args") or {}))
        for raw in (spec.get("steps") or [])
    )
    authority = str(spec.get("authority") or "proposal_only")
    problems: list[str] = []

    if not steps:
        problems.append("the plan has no steps")
    if authority not in AUTHORITIES:
        problems.append(f"authority {authority!r} is not one of {', '.join(sorted(AUTHORITIES))}")

    previous: str | None = None
    for index, step in enumerate(steps, 1):
        entry = functions.get(step.function)
        if entry is None:
            problems.append(f"step {index}: {step.function!r} is not a registered function")
            previous = None
            continue
        if entry.handler is None:
            problems.append(f"step {index}: {entry.name} is declared but has no handler (proposal only)")
        if index > 1 and previous is not None and entry.inputs:
            wanted = entry.inputs[0][1]
            if not functions.compatible(previous, wanted):
                problems.append(f"step {index}: {entry.name} wants {wanted}, but step {index - 1} gives {previous}")
        for param, kind in entry.inputs if index == 1 else entry.inputs[1:]:
            if param not in step.args and param not in entry.defaults:
                problems.append(f"step {index}: {entry.name} needs an argument for {param} ({kind})")
        previous = entry.output

    return Plan(
        name=str(name),
        title=str(spec.get("title") or name),
        authority=authority,
        steps=steps,
        problems=tuple(problems),
    )


def run(plan: Plan, ctx: functions.ToolContext, *, term: str = "") -> tuple[bool, str]:
    """Execute an admitted plan. Returns (ok, text) — a refusal is text, not an exception."""
    if not plan.admitted:
        return False, "refused at admission:\n" + "\n".join(f"  - {problem}" for problem in plan.problems)
    if plan.authority != "execute":
        return False, (
            f"{plan.name} is admitted as a {plan.authority} plan, so nothing was run.\n"
            "Its composition is valid; it just has no execution authority."
        )
    data: object = None
    for index, step in enumerate(plan.steps, 1):
        entry = functions.get(step.function)
        if entry is None or entry.handler is None:
            return False, f"step {index} ({step.function}) is not runnable"
        kwargs = {
            name: str(value).replace("{term}", term)
            for name, value in step.args.items()
        }
        if data is not None and entry.inputs:
            kwargs[entry.inputs[0][0]] = data
        try:
            data = entry.handler(ctx, **kwargs)
        except Exception as error:
            return False, f"step {index} ({entry.name}) failed: {error}"
    return True, str(data)
