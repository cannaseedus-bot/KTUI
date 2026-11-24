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
PROTOCOL = "kuhul-protocol/1"
DECODING = dict(temperature=0, max_tokens=900)
OUTPUT_SCHEMA = '{"phase": "Pop|Wo|Yax|Sek|Chen|Xul", "operators": ["<operator>", "..."], "authority": "proposal"}'
REGRESSION_CASES = ("pair-01", "pair-02", "phase-01", "uri-01", "authority-01", "unknown-01")
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


def digest_of(text: str) -> str:
    import hashlib
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def protocol(corpus: dict) -> dict:
    """Everything that must be identical across cells, recorded so a rerun can be reproduced."""
    variants = conditions()
    return dict(schema=PROTOCOL, case=CASE,
                contract_uri=variants["contract"]["contract_uri"],
                system_prompt_sha256=digest_of(system_prompt()),
                suffix_sha256={name: digest_of(spec["suffix"]) for name, spec in variants.items()},
                decoding=dict(DECODING), output_schema=OUTPUT_SCHEMA,
                expected_graph_sha256=corpus["by_id"][CASE].get("expected_graph_sha256"))


def cell_order(repeats: int, conditions_names: list[str]) -> list[list[str]]:
    """Interleave the conditions across repeats instead of blocking A, then B, then C."""
    order = []
    for repeat in range(max(1, int(repeats))):
        rotated = conditions_names[repeat % len(conditions_names):] + \
                  conditions_names[:repeat % len(conditions_names)]
        order.append(rotated)
    return order


def run(models: dict, corpus: dict, *, repeats: int = REPEATS, complete_for=None,
        interleave: bool = True) -> dict:
    case = corpus["by_id"].get(CASE)
    if case is None:
        raise KeyError(f"the frozen corpus has no case {CASE!r}")
    variants = conditions()
    results: dict[str, dict] = {}
    names = list(variants)
    order = cell_order(repeats, names) if interleave else [names for _ in range(max(1, int(repeats)))]
    for model, complete in (complete_for or {}).items():
        results[model] = {name: [] for name in names}
        for index, pass_order in enumerate(order):
            for name in pass_order:
                spec = variants[name]
                prompt = case["input"] + spec["suffix"]
                try:
                    reply = complete(prompt)
                    score = evaluation_harness.score_case(case, reply)
                    results[model][name].append(dict(run=index, parsed=score["parsed"],
                                                      verdict=score["verdict"],
                                      complete=score["complete"], nodes_ok=score["nodes_ok"],
                                      edges_ok=score["edges_ok"], proposed=score["proposed"],
                                      phase_ok=score.get("phase_ok"),
                                      targets_ok=score.get("targets_ok"),
                                      tokens=(score.get("tokens") or {}).get("total"),
                                      latency_ms=score.get("latency_ms"),
                                      finish_reason=score.get("finish_reason"),
                                      errors=score["errors"],
                                      reply_head=(reply.get("text") or "")[:240]))
                except Exception as error:
                    results[model][name].append(dict(run=index, parsed=False, complete=False,
                                                     error=f"{type(error).__name__}: {error}"[:160]))
        for name in names:
            cells = results[model][name]
            complete_cells = [cell for cell in cells if cell.get("complete")]
            results[model][name] = dict(
                repeats=len(cells), complete=len(complete_cells),
                rate=(len(complete_cells) / len(cells)) if cells else None,
                distinct_plans=len({json.dumps(cell.get("proposed")) for cell in cells
                                    if cell.get("proposed")}),
                cells=cells)
    return dict(schema=SCHEMA, case=CASE, repeats=int(repeats),
                protocol=protocol(corpus), interleaved=bool(interleave),
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
    parser.add_argument("--mode", choices=("conditions", "regression"), default="conditions")
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
    if args.mode == "regression":
        first = next(iter(completers))
        report = regression(first, corpus, complete_for=completers[first])
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(regression_summary(report))
        print(f"written: {args.out}")
        return 0
    report = run(completers, corpus, repeats=args.repeats, complete_for=completers)
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(summary(report))
    print(f"written: {args.out}")
    return 0



def regression(model: str, corpus: dict, *, complete_for, conditions_names=("baseline", "contract")) -> dict:
    """Does the contract help the full chain without hurting the simpler cases?

    The review's caution, as code: a structural instruction that fixes FOLD/ACCUMULATE must not be
    promoted for every micronaut before it is shown harmless on pairs, phase selection, refusals and
    unknown facts.
    """
    variants = conditions()
    report = dict(schema="kuhul-regression/1", model=model, cases=list(REGRESSION_CASES),
                  conditions={}, authority="declaration_only", execution=False,
                  note="per-category comparison; a promotion needs no regression here")
    for name in conditions_names:
        spec = variants[name]
        per_case = {}
        for case_id in REGRESSION_CASES:
            case = corpus["by_id"][case_id]
            try:
                reply = complete_for(case["input"] + spec["suffix"])
                score = evaluation_harness.score_case(case, reply)
                per_case[case_id] = dict(category=case["category"], complete=score["complete"],
                                         verdict=score["verdict"], parsed=score["parsed"],
                                         tokens=(score.get("tokens") or {}).get("total"))
            except Exception as error:
                per_case[case_id] = dict(category=case["category"], complete=False, parsed=False,
                                         error=f"{type(error).__name__}: {error}"[:140])
        report["conditions"][name] = dict(
            complete=sum(1 for cell in per_case.values() if cell.get("complete")),
            cases=len(per_case), detail=per_case)
    baseline = report["conditions"].get("baseline", {})
    contract = report["conditions"].get("contract", {})
    report["delta"] = (contract.get("complete", 0) - baseline.get("complete", 0))
    report["verdict"] = ("no_regression" if report["delta"] >= 0 else "regression")
    return report


def regression_summary(report: dict) -> str:
    lines = [f"regression · {report['model']} · {report['cases']} case(s) · verdict {report['verdict']}"]
    for name, block in report["conditions"].items():
        lines.append(f"  {name:9} {block['complete']}/{block['cases']} complete")
        for case_id, cell in block["detail"].items():
            lines.append(f"    {case_id:12} {cell['category']:20} complete={cell['complete']} "
                         f"{cell.get('verdict') or cell.get('error')}")
    lines.append(f"  delta {report['delta']:+d} (contract - baseline)")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
