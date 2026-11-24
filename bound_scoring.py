"""Three metrics that must not be merged: model structure, model binding, runtime binding.

The distinction the review asked for, as code:

    model_graph_exact        the model generated the required operator structure
    model_bound_complete     the model generated the structure AND the authorized target
    runtime_bound_complete   the host assembled a valid plan, whatever the model supplied

`runtime_bound_complete` is never credited to the model. A plan the host completed from a `wo_resolved`
binding is a valid runtime result and a model binding failure at the same time, and the report says both.
"""
from __future__ import annotations

import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
for _candidate in (str(HOST_ROOT / "kuhul-phase-engine-v0.1.0" / "core"), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import binding_resolver  # noqa: E402
import evaluation_harness  # noqa: E402
import plan_graph  # noqa: E402


def score_bound(case: dict, reply: dict, binding_record: dict) -> dict:
    """Score one reply three ways, keeping the attribution of every success explicit."""
    base = evaluation_harness.score_case(case, reply)
    sequence = plan_graph.parse_sequence(reply.get("text"))
    proposal = dict(sequence or {})
    if binding_record:
        applied = binding_resolver.apply_binding(binding_record, proposal)
    else:
        # No host binding: whatever the model said is the only source there is, and an omission is a
        # model omission - not an unmeasured field.
        target = proposal.get("target")
        applied = dict(ok=bool(target), binding_source=("model" if target else "missing"),
                       model_target=target, resolved_target=target, conflict=False,
                       reason=None if target else "the model supplied no target")
    graph_exact = base.get("verdict") == "exact"
    target_state = base.get("target_state")
    # The model must have produced the target itself for this to count as a model success.
    model_bound = bool(base.get("complete") and target_state in ("correct", "unbound"))
    # The runtime's plan is complete when the composition validly binds, regardless of who supplied it -
    # but never when the model asserted a target the case does not allow.
    runtime_bound = bool(graph_exact and base.get("phase_ok") is True
                         and applied.get("ok") and target_state != "incorrect"
                         and (target_state != "missing" or applied.get("binding_source") == "wo_resolved"
                              or applied.get("binding_source") == "none"))
    return dict(case=case.get("id"), category=case.get("category"),
                model_graph_exact=graph_exact,
                model_bound_complete=model_bound,
                runtime_bound_complete=runtime_bound,
                target_state=target_state,
                model_target=applied.get("model_target"),
                resolved_target=applied.get("resolved_target"),
                binding_source=applied.get("binding_source"),
                conflict=bool(applied.get("conflict")),
                binding_ok=bool(applied.get("ok")),
                verdict=base.get("verdict"), phase_ok=base.get("phase_ok"),
                parsed=base.get("parsed"), failed_requirements=base.get("failed_requirements"),
                reply_text=(reply.get("text") or "")[:4000])


def summarise(scores: list[dict]) -> dict:
    """Counts per metric, per case, with the attribution preserved."""
    cases: dict[str, dict] = {}
    for score in scores:
        bucket = cases.setdefault(score["case"], dict(case=score["case"], category=score["category"],
                                                      replies=0, graph=0, model_bound=0,
                                                      runtime_bound=0, conflicts=0,
                                                      wo_resolved=0, model_target=0, missing=0))
        bucket["replies"] += 1
        bucket["graph"] += int(score["model_graph_exact"])
        bucket["model_bound"] += int(score["model_bound_complete"])
        bucket["runtime_bound"] += int(score["runtime_bound_complete"])
        bucket["conflicts"] += int(score["conflict"])
        source = score.get("binding_source")
        bucket["wo_resolved"] += int(source == "wo_resolved")
        # the model's own target accuracy depends only on what it emitted, not on who bound the plan
        bucket["model_target"] += int(score.get("target_state") == "correct")
        bucket["missing"] += int(score["target_state"] == "missing")
    return dict(cases=cases, replies=len(scores),
                model_graph_exact=sum(1 for score in scores if score["model_graph_exact"]),
                model_bound_complete=sum(1 for score in scores if score["model_bound_complete"]),
                runtime_bound_complete=sum(1 for score in scores if score["runtime_bound_complete"]))


def summary(report: dict) -> str:
    lines = [f"bound scoring · {report['replies']} reply/replies · graph {report['model_graph_exact']} ·",
             f"model-bound {report['model_bound_complete']} · runtime-bound {report['runtime_bound_complete']}"]
    for case, bucket in report["cases"].items():
        lines.append(f"  {case:12} replies {bucket['replies']} · graph {bucket['graph']} · "
                     f"model-bound {bucket['model_bound']} · runtime-bound {bucket['runtime_bound']} · "
                     f"model-target {bucket['model_target']} · wo-resolved {bucket['wo_resolved']} · "
                     f"missing {bucket['missing']} · conflicts {bucket['conflicts']}")
    return "\n".join(lines)

def rescore_report(report: dict, corpus: dict, *, registry_record: dict | None = None) -> dict:
    """Re-derive every metric from the replies a report already stored - no new model calls."""
    import binding_resolver as resolver

    registry = registry_record or resolver.load()
    rebuilt = []
    for condition, block in (report.get("results") or {}).items():
        scores = []
        for entry in block.get("scores") or []:
            case = (corpus.get("by_id") or {}).get(entry.get("case"))
            if case is None or not entry.get("reply_text"):
                scores.append(dict(entry))
                continue
            binding = resolver.binding(registry, case["category"]) if block.get("binding") else None
            score = score_bound(case, dict(text=entry["reply_text"], model="stored"), binding)
            score["run"] = entry.get("run", 0)
            scores.append(score)
        rebuilt.append((condition, dict(block, scores=scores,
                                        summary=summarise([score for score in scores
                                                           if "model_graph_exact" in score]))))
    return dict(report, results={condition: block for condition, block in rebuilt},
                rescored=True,
                note=(report.get("note", "") + " | metrics re-derived offline from the stored replies; "
                      "no new inference"))

