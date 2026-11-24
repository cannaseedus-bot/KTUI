"""The A / C / E / CE comparison: profile and binding are independent inputs, measured separately.

    A    original profile, no binding
    C    examples profile, no binding
    E    original profile, Wo binding
    CE   examples profile, Wo binding

The point is not a combined completion score but attribution: if CE keeps C's graph correctness **and** reaches
E's runtime binding correctness, the two improvements compose; if it does not, the failure is localised.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import binding_resolver  # noqa: E402
import bound_scoring  # noqa: E402
import evaluation_harness  # noqa: E402
import session_profile  # noqa: E402

SCHEMA = "kuhul://experiment/ce/v1"
CASES = ("pair-01", "chain-01")
CONDITIONS = {
    "A": dict(profile="A_original", binding=False, note="original profile, no binding"),
    "C": dict(profile="C_contract_examples", binding=False, note="examples profile, no binding"),
    "E": dict(profile="A_original", binding=True, note="original profile, Wo binding"),
    "CE": dict(profile="C_contract_examples", binding=True, note="examples profile, Wo binding"),
}


def cases_for(corpus: dict, selection: str | None = None) -> list[str]:
    """`all` scores every frozen case; a comma list names categories or case ids explicitly."""
    if not selection or selection == "default":
        return list(CASES)
    if selection == "all":
        return [case["id"] for case in corpus.get("cases") or []
                if case.get("review_status") == "frozen"]
    wanted = [part.strip() for part in selection.split(",") if part.strip()]
    chosen = []
    for part in wanted:
        for case in corpus.get("cases") or []:
            if part in (case.get("id"), case.get("category")):
                chosen.append(case["id"])
    return chosen


def run(corpus: dict, *, complete_for, repeats: int = 1, conditions=tuple(CONDITIONS),
        cases: list[str] | None = None) -> dict:
    profiles = session_profile.load()
    registry = binding_resolver.load()
    case_ids = list(cases) if cases else list(CASES)
    results: dict[str, dict] = {}
    for name in conditions:
        spec = CONDITIONS[name]
        profile = profiles["profiles"][spec["profile"]]
        scores = []
        for case_id in case_ids:
            case = corpus["by_id"][case_id]
            binding = binding_resolver.binding(registry, case["category"])
            conversation = session_profile.messages(profile, case["input"])
            for index in range(max(1, int(repeats))):
                try:
                    reply = complete_for(conversation)
                    score = bound_scoring.score_bound(case, reply, binding if spec["binding"] else None)
                    score["run"] = index
                    scores.append(score)
                except Exception as error:
                    scores.append(dict(case=case_id, category=case["category"], run=index,
                                       parsed=False, model_graph_exact=False,
                                       model_bound_complete=False, runtime_bound_complete=False,
                                       target_state=None, conflict=False, binding_ok=False,
                                       binding_source=None, error=f"{type(error).__name__}: {error}"[:160]))
        results[name] = dict(condition=name, profile=spec["profile"], binding=spec["binding"],
                             note=spec["note"], summary=bound_scoring.summarise(scores),
                             scores=scores)
    return dict(schema=SCHEMA, cases=case_ids, repeats=int(repeats),
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                profiles={name: session_profile.profile_digest(profile)
                          for name, profile in profiles["profiles"].items()},
                results=results, authority="declaration_only", execution=False,
                note=("profile and binding are independently versioned inputs; runtime_bound_complete is "
                      "never credited as model target accuracy"))


def summary(report: dict) -> str:
    lines = ["condition  graph  model-bound  runtime-bound   (per case)"]
    for name, block in report["results"].items():
        summary = block["summary"]
        lines.append(f"  {name:3}  {summary['model_graph_exact']:5}  {summary['model_bound_complete']:11}  "
                     f"{summary['runtime_bound_complete']:13}")
        for case, bucket in summary["cases"].items():
            lines.append(f"        {case:10} graph {bucket['graph']}/{bucket['replies']} · "
                         f"model-bound {bucket['model_bound']} · runtime-bound {bucket['runtime_bound']} · "
                         f"model-target {bucket['model_target']} · wo-resolved {bucket['wo_resolved']} · "
                         f"conflicts {bucket['conflicts']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    import model_lifecycle

    parser = argparse.ArgumentParser(description="Compare profile and binding independently.")
    parser.add_argument("--model", default="planner")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cases", default="default",
                        help="default (pair-01, chain-01), all (every frozen case), or a comma list of "
                             "case ids / categories")
    parser.add_argument("--conditions", default="A,C,E,CE")
    parser.add_argument("--out", default=str(PACKAGE / "data" / "ce-experiment.json"))
    args = parser.parse_args(argv)
    corpus = evaluation_harness.load()
    declaration = model_lifecycle.load()
    entry = declaration["by_name"].get(args.model)
    if entry is None:
        print(f"unknown backend {args.model!r}")
        return 2
    # A session profile is a message list, so the completer must accept one; live_complete expects a prompt.
    complete = session_profile.complete(entry["base_url"], timeout=420)
    chosen = cases_for(corpus, args.cases)
    if not chosen:
        print(f"no frozen cases match {args.cases!r}")
        return 2
    conditions = tuple(part.strip() for part in args.conditions.split(",") if part.strip())
    unknown = [name for name in conditions if name not in CONDITIONS]
    if unknown:
        print(f"unknown conditions: {unknown}")
        return 2
    report = run(corpus, complete_for=complete, repeats=args.repeats, conditions=conditions,
                 cases=chosen)
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(summary(report))
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
