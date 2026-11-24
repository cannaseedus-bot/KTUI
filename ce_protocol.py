"""The frozen A-versus-CE protocol: specified before execution, reported without collapsing denominators.

Frozen before the run, so the protocol cannot drift while the numbers arrive:

    cases          every frozen case in the evaluation corpus, by id and expectation digest
    conditions     A (original profile, no binding) and CE (examples profile, Wo binding)
    repeats        3, interleaved by case and repeat so backend conditions cannot correlate with a condition
    scoring        kuhul://evaluation/scoring/v2, unchanged during the run

Every attempt is recorded with its outcome, because a transport failure is not a model failure:

    reply · empty_reply · http_error · timeout · cancelled

Reporting keeps the denominators apart - graph, phase, refusal, model-bound, runtime-bound and transport success -
and the accounting is derived from the artifact rather than from the plan:

    planned_calls 96 · attempted · received · scored · transport_failures
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.error
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

SCHEMA = "kuhul://experiment/protocol/v1"
REPORT = "kuhul://experiment/result/v1"
CONDITIONS = ("A", "CE")
SCORING = "kuhul://evaluation/scoring/v2"
REPEATS = 3
PROTOCOL_FILE = PACKAGE / "data" / "ce-protocol.json"


def freeze(corpus: dict, *, repeats: int = REPEATS) -> dict:
    """Write the protocol before any call, with the case digests it was frozen against."""
    cases = [case for case in corpus["cases"] if case.get("review_status") == "frozen"]
    record = dict(
        schema=SCHEMA, frozen_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        scoring=SCORING, repeats=int(repeats), conditions=list(CONDITIONS),
        planned_calls=len(cases) * len(CONDITIONS) * int(repeats),
        interleaved=True,
        cases=[dict(id=case["id"], category=case.get("category"),
                    expected_graph_sha256=case.get("expected_graph_sha256"),
                    contract=case.get("contract")) for case in cases],
        profiles={name: session_profile.profile_digest(profile)
                  for name, profile in session_profile.load()["profiles"].items()},
        rules=dict(
            interleave="alternate A and CE by case and repeat",
            transport=("record timeouts, HTTP errors, empty replies and cancellations as their own outcomes; a "
                       "transport failure is never a model failure"),
            separation=("frozen expectations are the scorer's; live Wo bindings come from kuhul://targets/v1 and "
                        "the two are never mixed"),
            scoring="v2, unchanged during the run; any later change is a separately versioned offline rescore",
            reporting=("by category, with graph, phase, refusal, model-bound, runtime-bound and transport "
                       "denominators kept apart"),
            runtime_bound_requires_refusal="a refusal case counts as runtime-bound only when it refused"),
        authority="declaration_only", execution=False)
    record["protocol_sha256"] = hashlib.sha256(
        json.dumps({key: record[key] for key in ("cases", "conditions", "repeats", "scoring")},
                   sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return record


def _classify(reply: dict | None, error: Exception | None) -> str:
    if error is not None:
        if isinstance(error, TimeoutError):
            return "timeout"
        if isinstance(error, urllib.error.HTTPError):
            return "http_error"
        if isinstance(error, KeyboardInterrupt):
            return "cancelled"
        return f"error:{type(error).__name__}"
    text = str((reply or {}).get("text") or "").strip()
    return "reply" if text else "empty_reply"


def run(corpus: dict, protocol: dict, *, complete_for, repeats: int | None = None) -> dict:
    registry = binding_resolver.load()
    profiles = session_profile.load()["profiles"]
    repeats = int(repeats or protocol["repeats"])
    cases = list(corpus["cases"])
    planned = [case for case in cases if case.get("review_status") == "frozen"]
    order = [name for name in CONDITIONS]
    results: dict[str, list[dict]] = {name: [] for name in order}
    started = time.monotonic()
    for repeat in range(repeats):
        for case in planned:
            sequence = order if (repeat + hash(case["id"])) % 2 == 0 else list(reversed(order))
            for name in sequence:
                profile = "C_contract_examples" if name == "CE" else "A_original"
                binding = binding_resolver.binding(registry, case["category"]) if name == "CE" else None
                conversation = session_profile.messages(profiles[profile], case["input"])
                reply, error = None, None
                try:
                    reply = complete_for(conversation)
                except Exception as problem:                      # noqa: BLE001 - classified, not swallowed
                    error = problem
                outcome = _classify(reply, error)
                cell = dict(case=case["id"], category=case.get("category"), condition=name,
                            repeat=repeat, outcome=outcome)
                if outcome == "reply":
                    score = bound_scoring.score_bound(case, reply, binding)
                    score.update(repeat=repeat, outcome=outcome, condition=name)
                    cell.update(score)
                else:
                    cell.update(dict(model_graph_exact=None, model_bound_complete=None,
                                     runtime_bound_complete=None, phase_ok=None,
                                     target_state=None, conflict=False, binding_source=None,
                                     model_target=None, resolved_target=None,
                                     error=f"{type(error).__name__}: {error}"[:200] if error else None))
                results[name].append(cell)
    return dict(schema=REPORT, protocol_sha256=protocol["protocol_sha256"],
                cases=[case["id"] for case in planned], repeats=repeats,
                conditions=list(CONDITIONS), duration_ms=int(round((time.monotonic() - started) * 1000)),
                results=results, accounting=_accounting(results, protocol["planned_calls"]),
                by_category=_by_category(results), authority="declaration_only", execution=False,
                note=("measured internal regression evidence, not independently validated accuracy; "
                      "denominators are reported apart"))


def _accounting(results: dict, planned_calls: int) -> dict:
    cells = [cell for rows in results.values() for cell in rows]
    return dict(
        planned_calls=planned_calls, attempted_calls=len(cells),
        responses_received=sum(1 for cell in cells if cell["outcome"] == "reply"),
        responses_scored=sum(1 for cell in cells if cell.get("verdict") is not None),
        transport_failures=sum(1 for cell in cells if cell["outcome"] != "reply"),
        outcomes={outcome: sum(1 for cell in cells if cell["outcome"] == outcome)
                  for outcome in sorted({cell["outcome"] for cell in cells})})


def _by_category(results: dict) -> dict:
    categories: dict[str, dict] = {}
    for condition, rows in results.items():
        for cell in rows:
            bucket = categories.setdefault(cell["category"], {})
            block = bucket.setdefault(condition, dict(cells=0, transport_ok=0, graph=0, phase=0,
                                                       refusal_ok=0, model_bound=0, runtime_bound=0))
            block["cells"] += 1
            block["transport_ok"] += int(cell["outcome"] == "reply")
            if cell["outcome"] == "reply":
                block["graph"] += int(bool(cell.get("model_graph_exact")))
                block["phase"] += int(cell.get("phase_ok") is True)
                block["refusal_ok"] += int(cell.get("verdict") is not None
                                            and cell.get("model_bound_complete") is not None
                                            and bool(cell.get("runtime_bound_complete"))
                                            and (cell.get("target_state") == "unbound"))
                block["model_bound"] += int(bool(cell.get("model_bound_complete")))
                block["runtime_bound"] += int(bool(cell.get("runtime_bound_complete")))
    return dict(sorted(categories.items()))


def summary(report: dict) -> str:
    accounting = report["accounting"]
    lines = [f"A vs CE · {accounting['planned_calls']} planned · {accounting['attempted_calls']} attempted · "
             f"{accounting['responses_received']} received · {accounting['responses_scored']} scored · "
             f"{accounting['transport_failures']} transport failures · {report['duration_ms']} ms"]
    for category, blocks in report["by_category"].items():
        cells = []
        for condition in CONDITIONS:
            block = blocks.get(condition) or {}
            if not block:
                continue
            cells.append(f"{condition}: graph {block['graph']}/{block['cells']} "
                         f"phase {block['phase']} model-bound {block['model_bound']} "
                         f"runtime-bound {block['runtime_bound']} transport {block['transport_ok']}")
        lines.append(f"  {category:22} " + " | ".join(cells))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    import model_lifecycle

    parser = argparse.ArgumentParser(description="Freeze, then run, the A-versus-CE protocol.")
    parser.add_argument("--model", default="planner")
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--out", default=str(PACKAGE / "data" / "ce-run.json"))
    args = parser.parse_args(argv)
    corpus = evaluation_harness.load()
    protocol_path = PROTOCOL_FILE
    if args.freeze_only or not protocol_path.is_file():
        protocol = freeze(corpus, repeats=args.repeats)
        protocol_path.write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
        print(f"frozen: {protocol_path} · {protocol['planned_calls']} planned calls · "
              f"sha {protocol['protocol_sha256'][:16]}")
        if args.freeze_only:
            return 0
    else:
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        print(f"using frozen protocol {protocol['protocol_sha256'][:16]} "
              f"({protocol['planned_calls']} planned calls)")
    declaration = model_lifecycle.load()
    entry = declaration["by_name"].get(args.model)
    if entry is None:
        print(f"unknown backend {args.model!r}")
        return 2
    complete = session_profile.complete(entry["base_url"], timeout=420)
    report = run(corpus, protocol, complete_for=complete)
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(summary(report))
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
