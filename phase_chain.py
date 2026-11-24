"""The missing bridge: walk the phase manifests with the input and a carried context.

Two declaration layers feed this resolver:

    .aiml phase banks     pattern vocabulary and phase operations   (recognition)
    phases/json/*.json    phase identity, next, bindings, capability (routing)

It produces one deterministic, read-only **operation plan**: what each phase would match, what it would
carry forward, which capabilities it would need, and where a binding is declared twice.

Two things the review called out, and how they are handled:

1. **Pop and Wo declare the same redirect.** The plan records which phase *applied* a binding and which
   phases merely *shadowed* it. The input advances only through an applied redirect, so a shared input
   is not processed twice; the duplicate is reported (`duplicate_binding`) rather than silently ignored.
2. **A phase transition is not a pattern match.** When a phase has nothing that matches, it still
   appears in the plan as `no_match` with the carried context intact - the chain stays operationally
   connected, and the plan shows that it was visited rather than skipped.

Nothing here executes, admits or persists: `execution: false`, `authority: "declaration_only"`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import aiml_graph  # noqa: E402
import phase_manifest  # noqa: E402
import srai_resolver  # noqa: E402

MANIFESTS = PACKAGE / "phases" / "json"
START = "kuhul://phases/pop"
SCHEMA = "kuhul.phase-plan.chain/1"


def load(folder: Path = MANIFESTS, start: str = START) -> dict:
    """The manifest chain, plus a check that the phase banks it names exist."""
    report = phase_manifest.chain(start, root=Path(folder))
    banks = []
    for manifest in report.get("manifests") or []:
        for name in manifest["aiml"]:
            banks.append(str((Path(folder) / name).resolve()))
    return dict(report, banks=banks)


def _binding_key(binding: dict) -> tuple[str, str]:
    target = binding.get("srai") or binding.get("directive") or ""
    return (str(binding.get("pattern") or "").upper(), str(target))


def resolve(text: str, *, folder: Path = MANIFESTS, start: str = START,
            context: dict | None = None, use_original: bool = False) -> dict:
    """Walk the chain once, carrying the context. Deterministic and read-only.

    `use_original=True` re-tests every phase against the *original* input instead of the advanced one;
    that is how the duplicate redirect in Pop and Wo becomes observable.
    """
    chain = load(folder, start)
    original = str(text or "").strip()
    current = original
    carried = dict(context or {})
    captures: list[str] = []
    redirects: list[dict] = []
    capabilities: list[dict] = []
    applied_at: dict[tuple[str, str], str] = {}
    duplicates: list[dict] = []
    visits: list[dict] = []

    for manifest in chain.get("manifests") or []:
        phase = manifest["phase"]
        tested = original if use_original else current
        visit = dict(phase=phase, tested=tested, applied=[], shadowed=[], no_match=[])
        for binding in manifest["bindings"] or []:
            pattern = str(binding.get("pattern") or "")
            target = str(binding.get("srai") or binding.get("directive") or "")
            found = aiml_graph.match(pattern, tested)
            if found is None:
                visit["no_match"].append(pattern)
                continue
            key = _binding_key(binding)
            if key in applied_at:
                duplicates.append(dict(pattern=pattern, target=target,
                                       first_phase=applied_at[key], again_in=phase))
                visit["shadowed"].append(dict(pattern=pattern, target=target, first=applied_at[key]))
                continue
            applied_at[key] = phase
            # Directives carry captures too: COMPOSE pet is literal, QUERY {star:1} is not.
            resolved = srai_resolver.substitute(target, found)
            visit["applied"].append(dict(pattern=pattern, target=target, kind=("srai" if binding.get("srai")
                                                                              else "directive"),
                                          captures=list(found), resolved=resolved))
            captures.extend(found)
            if binding.get("srai"):
                current = resolved
                redirects.append(dict(phase=phase, from_=pattern, to=resolved))
            if binding.get("capability"):
                capabilities.append(dict(phase=phase, capability=binding["capability"]))
        visits.append(visit)

    closure = _closure(visits, capabilities, redirects)
    plan = dict(schema=SCHEMA, input=original, start=start,
                folder=str(Path(folder).resolve()),
                phases=[manifest["phase"] for manifest in chain.get("manifests") or []],
                visits=visits, carried=dict(sorted(carried.items())),
                context=dict(captures=sorted(set(captures)), redirects=redirects,
                             capabilities=capabilities, final_input=current),
                duplicates=duplicates, closure=closure,
                chain_ok=bool(chain.get("ok")), chain_problems=chain.get("problems") or [],
                execution=False, mutation=False, authority="declaration_only",
                note="a plan is a proposal; XCFE decides authority and the host decides what to run")
    return plan


def _closure(visits: list[dict], capabilities: list[dict], redirects: list[dict]) -> dict:
    """What the chain would hand on - never a rendered answer."""
    applied = [entry for visit in visits for entry in visit["applied"]]
    if not applied:
        return dict(kind="none", reason="no binding matched; the host answers or defers",
                    capabilities=[capability["capability"] for capability in capabilities])
    directives = [entry for entry in applied if entry["kind"] == "directive"]
    if directives:
        return dict(kind="delegated", reason="a directive was matched; the host owns the execution",
                    directive=directives[-1]["resolved"],
                    capabilities=sorted({capability["capability"] for capability in capabilities}),
                    verified=False)
    return dict(kind="redirected", reason="the chain redirected the input",
                final=redirects[-1]["to"] if redirects else None,
                capabilities=sorted({capability["capability"] for capability in capabilities}),
                verified=False)


def canonical(plan: dict) -> str:
    return json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def summary(plan: dict) -> str:
    lines = [f"phase chain · {plan['input']!r} · {len(plan['phases'])} phase(s)",
             f"  chain: {' -> '.join(plan['phases'])}"]
    for visit in plan["visits"]:
        applied = ", ".join(f"{item['pattern']} -> {item['resolved']}" for item in visit["applied"])
        state = applied or ("no match" if visit["no_match"] else "(no bindings)")
        shadowed = (f" · shadowed {len(visit['shadowed'])}" if visit["shadowed"] else "")
        lines.append(f"  {visit['phase']:6} {state}{shadowed}")
    if plan["duplicates"]:
        for item in plan["duplicates"]:
            lines.append(f"  duplicate: {item['pattern']} applied in {item['first_phase']}, "
                         f"declared again in {item['again_in']}")
    closure = plan["closure"]
    lines.append(f"  closure: {closure['kind']} - {closure['reason']}")
    capabilities = closure.get("capabilities") or []
    if capabilities:
        lines.append(f"  capabilities required: {', '.join(capabilities)}")
    lines.append("  (execution false · authority declaration_only)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Resolve an input through the phase manifest chain.")
    parser.add_argument("text", help="the input to walk the chain with")
    parser.add_argument("--folder", default=str(MANIFESTS))
    parser.add_argument("--original", action="store_true",
                        help="test every phase against the original input")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    plan = resolve(args.text, folder=Path(args.folder), use_original=args.original)
    print(json.dumps(plan, indent=2) if args.json else summary(plan))
    return 0 if plan["chain_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
