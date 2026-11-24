"""The clean two-condition experiment: baseline instruction vs the versioned operator contract.

The previous comparison (M51) had a confound I created - the system prompt changed between the baseline and
the conditions. This one removes it by construction:

    one system prompt, identical in both conditions, recorded in the result
    one case, one frozen expected graph, one validator
    the baseline instruction is frozen above the contract run, so the original numbers stay comparable
    every cell repeats, so sampling noise is measured rather than assumed away

The contract text is **rendered from `kuhul://operators/v1`**, the same declaration `plan_graph` validates
against, so the prompt cannot drift from the rules.
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

import evaluation_harness  # noqa: E402
import plan_graph  # noqa: E402
import proposal_eval  # noqa: E402

SCHEMA = "kuhul-contract-experiment/1"
CASE = "chain-01"
REPEATS = 3
# The baseline is frozen here, above the results, so a later prompt change cannot quietly rewrite it.
BASELINE_SUFFIX = ""


def system_prompt() -> str:
    """One system prompt for both conditions. This is the variable that was not held fixed before."""
    return proposal_eval.SYSTEM


def conditions() -> dict:
    loaded = plan_graph.contract()
    if not loaded["ok"]:
        raise RuntimeError(f"the operator contract does not load: {loaded['problems']}")
    return {
        "baseline": dict(
            suffix=BASELINE_SUFFIX,
            note="the original ambiguous instruction, unchanged",
            contract_uri=None),
        "contract": dict(
            suffix="\n\n" + plan_graph.render_contract_prompt(loaded["record"]),
            note="the same instruction plus kuhul://operators/v1, rendered from the declaration",
            contract_uri=loaded["uri"]),
    }


def run(models: dict, corpus: dict, *, repeats: int = REPEATS, complete_for=None) -> dict:
    case = corpus["by_id"].get(CASE)
    if case is None:
        raise KeyError(f"the frozen corpus has no case {CASE!r}")
    variants = conditions()
    results: dict[str, dict] = {}
    for model, complete in (complete_for or {}).items():
        results[model] = {}
        for name, spec in variants.items():
            cells = []
            for index in range(max(1, int(repeats))):
                prompt = case["input"] + spec["suffix"]
                try:
                    reply = complete(prompt)
                    score = evaluation_harness.score_case(case, reply)
                    cells.append(dict(run=index, parsed=score["parsed"], verdict=score["verdict"],
                                      complete=score["complete"], nodes_ok=score["nodes_ok"],
                                      edges_ok=score["edges_ok"], proposed=score["proposed"],
                                      tokens=(score.get("tokens") or {}).get("total"),
                                      latency_ms=score.get("latency_ms"),
                                      finish_reason=score.get("finish_reason"),
                                      errors=score["errors"],
                                      reply_head=(reply.get("text") or "")[:240]))
                except Exception as error:
                    cells.append(dict(run=index, parsed=False, complete=False,
                                      error=f"{type(error).__name__}: {error}"[:160]))
            complete_cells = [cell for cell in cells if cell.get("complete")]
            results[model][name] = dict(
                repeats=len(cells), complete=len(complete_cells),
                rate=(len(complete_cells) / len(cells)) if cells else None,
                distinct_plans=len({json.dumps(cell.get("proposed")) for cell in cells
                                    if cell.get("proposed")}),
                cells=cells)
    return dict(schema=SCHEMA, case=CASE, repeats=int(repeats),
                system_prompt=system_prompt(),
                baseline_frozen=dict(case=CASE, suffix=BASELINE_SUFFIX, note="kept unchanged"),
                conditions={name: dict(note=spec["note"], contract_uri=spec["contract_uri"])
                            for name, spec in variants.items()},
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                results=results, authority="declaration_only", execution=False,
                note=("one frozen case, repeated per cell, identical system prompt in both conditions; "
                      "exact graph equivalence is the only success criterion"))


def summary(report: dict) -> str:
    lines = [f"contract experiment · case {report['case']} · {report['repeats']} repeat(s) · "
             f"system prompt held fixed"]
    lines.append("  " + "model".ljust(10) + "baseline".ljust(18) + "contract".ljust(18))
    for model, cells in report["results"].items():
        cells_text = ""
        for name in ("baseline", "contract"):
            cell = cells.get(name) or {}
            cells_text += f"{cell.get('complete', 0)}/{cell.get('repeats', 0)} exact".ljust(18)
        lines.append("  " + model.ljust(10) + cells_text)
    for model, cells in report["results"].items():
        for name, cell in cells.items():
            verdicts = {}
            for item in cell["cells"]:
                key = str(item.get("verdict") or item.get("error") or "unparsed")
                verdicts[key] = verdicts.get(key, 0) + 1
            lines.append(f"  {model:8} {name:9} complete {cell['complete']}/{cell['repeats']}"
                         f" · verdicts {verdicts}"
                         f" · plans {cell['distinct_plans']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    import model_lifecycle

    parser = argparse.ArgumentParser(description="Baseline vs the operator contract, cleanly.")
    parser.add_argument("--models", default="worker,planner")
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--out", default=str(PACKAGE / "data" / "contract-experiment.json"))
    args = parser.parse_args(argv)
    corpus = evaluation_harness.load()
    declaration = model_lifecycle.load()
    completers = {}
    for name in [part.strip() for part in args.models.split(",") if part.strip()]:
        entry = declaration["by_name"].get(name)
        if entry is None:
            print(f"unknown backend {name!r}")
            continue
        completers[name] = proposal_eval.live_complete(entry["base_url"], timeout=420)
    report = run(completers, corpus, repeats=args.repeats, complete_for=completers)
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(summary(report))
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
