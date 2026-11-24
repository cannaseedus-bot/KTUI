"""Three instruction conditions against one frozen graph validator: baseline, semantic, structural.

The measured fact this exists to explain: gemma-3-1b and gpt-oss-20b produced the **same** plan -
`filter, map, accumulate, reduce` - despite a 10.6x latency gap. Identical errors do not show that either
model cannot build the right graph; they show that the instruction did not distinguish it.

    A baseline    "accumulate evidence"                          the ambiguous phrasing
    B semantic    "FOLD owns ACCUMULATE; REDUCE follows FOLD"    the contract in plain words
    C structural  the typed contract: containment, execution     the grammar itself

Scored by `evaluation_harness.score_case`, so the validator is the same one the frozen corpus uses and
nothing is weakened to make a condition look better.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import evaluation_harness  # noqa: E402
import proposal_eval  # noqa: E402

SCHEMA = "kuhul-condition-experiment/1"
CASE = "chain-01"

CONTRACT = (
    "K'UHUL OPERATOR CONTRACT\n"
    "FILTER selects matching items.\n"
    "MAP transforms selected items.\n"
    "FOLD owns the accumulation state.\n"
    "ACCUMULATE is nested inside FOLD.\n"
    "REDUCE consumes the completed FOLD result.\n"
    "Execution order: FILTER -> MAP -> FOLD -> REDUCE\n"
    "Containment: FOLD -> ACCUMULATE\n"
    "Do not replace FOLD with ACCUMULATE.\n"
    "Do not add operators beyond the requested graph.\n"
    "Return only the declared proposal structure.\n"
    "Authority must be \"proposal\"."
)

CONDITIONS = {
    "A_baseline": dict(
        suffix="",
        note="the original ambiguous phrasing"),
    "B_semantic": dict(
        suffix=" FOLD owns ACCUMULATE; REDUCE follows FOLD.",
        note="the contract in plain words, appended to the same instruction"),
    "C_structural": dict(
        suffix="\n\n" + CONTRACT,
        note="the typed contract: containment, execution order and authority stated explicitly"),
}


def instructions(corpus: dict) -> dict:
    """The instruction each condition sends, per case - the case text is never altered beyond the suffix."""
    case = corpus["by_id"].get(CASE)
    if case is None:
        raise KeyError(f"the frozen corpus has no case {CASE!r}")
    return {name: case["input"] + spec["suffix"] for name, spec in CONDITIONS.items()}


def run(models: dict, corpus: dict, *, conditions=tuple(CONDITIONS), complete_for=None) -> dict:
    """Run each condition on each model against the same frozen case and score with the same validator."""
    case = corpus["by_id"][CASE]
    prompts = instructions(corpus)
    results: dict[str, dict] = {}
    for model, complete in (complete_for or {}).items():
        results[model] = {}
        for condition in conditions:
            if condition not in CONDITIONS:
                raise KeyError(f"unknown condition {condition!r}")
            try:
                reply = complete(prompts[condition])
            except Exception as error:
                results[model][condition] = dict(error=f"{type(error).__name__}: {error}"[:160],
                                                 parsed=False, complete=False)
                continue
            score = evaluation_harness.score_case(case, reply)
            results[model][condition] = dict(
                parsed=score["parsed"], verdict=score["verdict"], complete=score["complete"],
                nodes_ok=score["nodes_ok"], edges_ok=score["edges_ok"],
                proposed=score["proposed"],
                tokens=(score.get("tokens") or {}).get("total"),
                latency_ms=score.get("latency_ms"), finish_reason=score.get("finish_reason"),
                errors=score["errors"], reply_head=(reply.get("text") or "")[:300])
    return dict(schema=SCHEMA, case=CASE, models=models and sorted(results),
                conditions={name: CONDITIONS[name]["note"] for name in conditions},
                results=results, authority="declaration_only", execution=False,
                note=("one frozen case, one run per cell: this separates instruction effects from model "
                      "size, it does not estimate general capability"))


def summary(report: dict) -> str:
    lines = [f"condition experiment · case {report['case']} · {len(report['results'])} model(s)"]
    header = "  " + "condition".ljust(14) + "".join(name.ljust(18) for name in report["results"])
    lines.append(header)
    rows = list(report["results"].values())
    for condition in list(rows[0].keys()) if rows else []:
        cells = []
        for model, cell in report["results"].items():
            outcome = cell.get(condition, {})
            cells.append((outcome.get("verdict") or outcome.get("error") or "-")[:17].ljust(18))
        lines.append("  " + condition.ljust(14) + "".join(cells))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Live run against the declared backends; every metric recorded comes from the server."""
    import argparse
    import time

    import model_lifecycle  # noqa: E402

    parser = argparse.ArgumentParser(description="Run the three conditions on the live backends.")
    parser.add_argument("--models", default="worker,planner", help="comma separated backend names")
    parser.add_argument("--out", default=str(PACKAGE / "data" / "condition-experiment.json"))
    args = parser.parse_args(argv)
    corpus = evaluation_harness.load()
    declaration = model_lifecycle.load()
    completers = {}
    timeouts = {"worker": 300, "planner": 300, "advisor": 420}
    for name in [part.strip() for part in args.models.split(",") if part.strip()]:
        entry = declaration["by_name"].get(name)
        if entry is None:
            print(f"unknown backend {name!r}")
            continue
        completers[name] = proposal_eval.live_complete(entry["base_url"],
                                                       timeout=timeouts.get(name, 300))
    report = run(completers, corpus, complete_for=completers)
    report["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(summary(report))
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
