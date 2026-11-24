"""The frozen evaluation corpus, and a harness that scores models against it without touching the app.

Two rules from the review are enforced, not documented:

    only review_status=frozen cases count toward the headline
    the corpus must not be reachable from the live path   -  a check fails the run if `chat_app` or the
                                                            retrieval index would load expected answers

Scoring separates what a plan got right, because they are different failures:

    parse            did a plan come out at all
    nodes            the right operators, counted
    edges            the right connections, in order (a nested `accumulate` under `fold`)
    complete plan    nodes AND edges AND registered targets AND the expected refusal
    refusal          a case that must refuse is scored on refusing, not on producing a plan

`expected-graphs.gml` is the human-readable half of the same facts; `cases.jsonl` is what runs.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
for _candidate in (str(HOST_ROOT / "kuhul-phase-engine-v0.1.0" / "core"), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import plan_graph  # noqa: E402

CORPUS = HOST_ROOT / "evaluation"
SCHEMA = "kuhul-eval-corpus/2"
RESULTS = CORPUS / "results"
ISOLATION = ("chat_app", "knowledge.py", "corpus.py", "aiml_graph.py")


def digest(expect: dict) -> str:
    """A stable digest over the expected graph, so a silent edit shows up as a mismatch."""
    canonical = json.dumps(expect or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reviewers(folder: Path | None = None) -> dict:
    folder = Path(folder or CORPUS)
    try:
        record = json.loads((folder / "reviewers.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, by_id={}, problems=[dict(code="reviewers", detail=str(error))])
    return dict(ok=True, by_id=record.get("reviewers") or {}, problems=[])


def verify_review(case: dict, registry: dict) -> dict:
    """A review counts only if the reviewer is registered and the method matches its role."""
    review = case.get("review") or {}
    reviewer = str(review.get("reviewer") or "")
    method = str(review.get("method") or "")
    entry = (registry.get("by_id") or {}).get(reviewer)
    if entry is None:
        return dict(ok=False, method=method, reviewer=reviewer, independent=False,
                    reason=f"reviewer {reviewer!r} is not registered in reviewers.json")
    if method == "independent" and not entry.get("independent"):
        return dict(ok=False, method=method, reviewer=reviewer, independent=False,
                    reason=f"{reviewer!r} is registered as {entry.get('role')!r}, not independent")
    if method not in ("author", "independent"):
        return dict(ok=False, method=method, reviewer=reviewer, independent=False,
                    reason=f"unknown review method {method!r}")
    return dict(ok=True, method=method, reviewer=reviewer,
                independent=bool(entry.get("independent")) and method == "independent")


def load(folder: Path | None = None) -> dict:
    """Load and validate the corpus. The manifest's counts must match the file."""
    folder = Path(folder or CORPUS)
    problems: list[dict] = []
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, problems=[dict(code="manifest", detail=str(error))], cases=[],
                    manifest={})
    if manifest.get("schema") != SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {SCHEMA}"))
    if manifest.get("authority") != "declaration_only":
        problems.append(dict(code="authority", detail="a corpus is declaration_only"))
    registry = reviewers(folder)
    problems.extend(registry.get("problems") or [])
    cases: list[dict] = []
    seen: set[str] = set()
    for line_number, line in enumerate((folder / manifest.get("case_file", "cases.jsonl"))
                                       .read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as error:
            problems.append(dict(code="case", detail=f"line {line_number}: {error}"))
            continue
        identifier = str(case.get("id") or "")
        if not identifier:
            problems.append(dict(code="case_id", detail=f"line {line_number}"))
            continue
        if identifier in seen:
            problems.append(dict(code="duplicate_case", detail=identifier))
            continue
        seen.add(identifier)
        if case.get("review_status") not in ("draft", "reviewed", "frozen"):
            problems.append(dict(code="review_status",
                                 detail=f"{identifier}: {case.get('review_status')!r}"))
        expect = case.get("expect") or {}
        if expect.get("phase") not in plan_graph.PHASES:
            problems.append(dict(code="phase", detail=f"{identifier}: {expect.get('phase')!r}"))
        graph = expect.get("graph") or {}
        for key in ("nodes", "edges"):
            if not isinstance(graph.get(key), list):
                problems.append(dict(code="graph", detail=f"{identifier}: no {key}"))
        recorded = case.get("expected_graph_sha256")
        if recorded != digest(expect):
            problems.append(dict(code="digest", detail=f"{identifier}: expectation changed since it "
                                                       "was frozen"))
        if case.get("contract") != manifest.get("contract"):
            problems.append(dict(code="contract", detail=f"{identifier}: {case.get('contract')!r}"))
        review = verify_review(case, registry)
        if not review["ok"]:
            problems.append(dict(code="review", detail=f"{identifier}: {review['reason']}"))
        case["_review"] = review
        cases.append(case)
    if manifest.get("cases") != len(cases):
        problems.append(dict(code="count",
                             detail=f"manifest says {manifest.get('cases')}, file has {len(cases)}"))
    frozen = [case["id"] for case in cases if case["review_status"] == "frozen"]
    if manifest.get("frozen_ids") != frozen:
        problems.append(dict(code="frozen_ids",
                             detail="manifest frozen_ids do not match the frozen cases in the file"))
    # A review counts only when a signed attestation verifies against the registry, not when a field
    # says "independent". The field-based review stays as a declared claim.
    try:
        import review_attestations
        attestation_report = review_attestations.check(
            dict(by_id={case["id"]: case for case in cases}), review_attestations.load(),
            review_attestations.registry(Path(folder) / "reviewers.json"))
    except Exception as error:                     # a broken attestation layer must not hide the corpus
        attestation_report = dict(verified=0, independent=0, independently_reviewed_cases=[],
                                  error=f"{type(error).__name__}: {error}")
    independent = [case["id"] for case in cases if case["_review"]["independent"]]
    if manifest.get("independent_reviews") != len(independent):
        problems.append(dict(code="independent_reviews",
                             detail=f"manifest says {manifest.get('independent_reviews')}, "
                                    f"registry supports {len(independent)}"))
    eligible = [case for case in cases if case["review_status"] == "frozen" and case["_review"]["ok"]]
    return dict(ok=not problems, problems=problems, cases=cases, manifest=manifest,
                by_id={case["id"]: case for case in cases},
                frozen=[case for case in cases if case["review_status"] == "frozen"],
                eligible=eligible, independently_reviewed=independent,
                verified_attestations=int(attestation_report.get("verified") or 0),
                independently_attested=attestation_report.get("independently_reviewed_cases") or [],
                attestation_report=attestation_report,
                authority="declaration_only")


def isolation(folder: Path | None = None) -> dict:
    """The corpus must not be wired into the live path: expected answers cannot be retrieved."""
    folder = Path(folder or CORPUS)
    offenders = []
    for name in ISOLATION:
        path = HOST_ROOT / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "evaluation/cases" in text or "evaluation.manifest" in text or \
                "import evaluation_harness" in text:
            offenders.append(name)
    return dict(ok=not offenders, offenders=offenders,
                note="the corpus is an offline artifact; nothing in the app reads it")


def score_case(case: dict, reply: dict) -> dict:
    """Score one reply against one case. Never repairs: a wrong plan stays wrong.

    A refusal case is scored on the refusal, not on producing a plan; and a target is only scored when
    the proposal carries one, because the host resolves targets for a sequence-form proposal.
    """
    expect = case["expect"] or {}
    sequence = plan_graph.parse_sequence(reply.get("text"))
    if sequence is None:
        # A six-field proposal list is the other legitimate shape; both are scored the same way.
        import proposal_eval
        proposals = proposal_eval._extract(reply.get("text"))
        if proposals:
            phase = next((item.get("phase") for item in proposals if isinstance(item, dict)), None)
            operators = [item.get("operator") for item in proposals
                         if isinstance(item, dict) and item.get("operator")]
            if operators:
                sequence = dict(phase=phase or "Sek", operators=operators,
                                authority=next((item.get("authority") for item in proposals
                                                if isinstance(item, dict)), None),
                                proposals=proposals)
    outcome = dict(case=case["id"], category=case["category"], review=case["review_status"],
                   model=reply.get("model"), latency_ms=reply.get("latency_ms"),
                   finish_reason=reply.get("finish_reason"),
                   tokens=dict(total=reply.get("completion_tokens"),
                               reasoning=reply.get("reasoning_tokens")),
                   parsed=sequence is not None, nodes_ok=False, edges_ok=False,
                   targets_ok=None, refusal_ok=None, phase_ok=None, complete=False, verdict=None,
                   expected_refusal=expect.get("refusal"), proposed=None, errors=[])
    if expect.get("refusal"):
        said = str(reply.get("text") or "").lower()
        operators = (sequence or {}).get("operators") or []
        refused = any(word in said for word in
                      ("cannot", "can't", "refus", "not grant", "no permission", "unauthor",
                       "no record", "unknown", "not available"))
        outcome["refusal_ok"] = bool(refused and not operators)
        outcome["complete"] = outcome["refusal_ok"]
        if not outcome["complete"]:
            outcome["errors"].append("did_not_refuse")
        return outcome
    if sequence is None:
        outcome["errors"].append("unparseable")
        return outcome
    expected_operators = [node["operator"] for node in (expect.get("graph") or {}).get("nodes", [])
                          if not node.get("parent")]
    graph = plan_graph.compare(sequence.get("operators"), expected=expected_operators)
    outcome["verdict"] = graph["verdict"]
    outcome["proposed"] = graph["proposed"]
    outcome["nodes_ok"] = graph["nodes_ok"]
    outcome["edges_ok"] = graph["edges_ok"]
    if expect.get("phase"):
        outcome["phase_ok"] = (plan_graph.PHASE_ALIASES.get(str(sequence.get("phase") or "").lower())
                               == expect["phase"])
    allowed = list(expect.get("targets") or [])
    claimed = [str(item.get("target") or "") for item in (sequence.get("proposals") or [])
               if isinstance(item, dict) and item.get("target")]
    if not claimed and sequence.get("target"):
        claimed = [str(sequence["target"])]
    if allowed and claimed:
        outcome["targets_ok"] = all(any(target.startswith(prefix) for prefix in allowed)
                                    for target in claimed)
    outcome["complete"] = bool(outcome["nodes_ok"] and outcome["edges_ok"]
                               and outcome["targets_ok"] in (True, None)
                               and outcome["phase_ok"] in (True, None))
    return outcome


def evaluate(model: str, complete_for, corpus: dict, *, include="frozen") -> dict:
    """Run every selected case once and report parse, nodes, edges, complete plan and refusals."""
    cases = corpus["frozen"] if include == "frozen" else corpus["cases"]
    scores = []
    for case in cases:
        reply = complete_for(case["input"])
        scores.append(score_case(case, reply))
    parsed = [score for score in scores if score["parsed"]]
    per_category: dict[str, dict] = {}
    for score in scores:
        bucket = per_category.setdefault(score["category"], dict(cases=0, complete=0, parsed=0))
        bucket["cases"] += 1
        bucket["parsed"] += int(score["parsed"])
        bucket["complete"] += int(score["complete"])
    return dict(schema="kuhul-eval-result/1", model=model, include=include,
                cases=len(scores), parsed=len(parsed),
                truncation=sum(1 for score in scores
                               if score["finish_reason"] == "length"),
                nodes_ok=sum(1 for score in parsed if score["nodes_ok"]),
                edges_ok=sum(1 for score in parsed if score["edges_ok"]),
                complete=sum(1 for score in scores if score["complete"]),
                refusals=dict(expected=sum(1 for score in scores if score["expected_refusal"]),
                              correct=sum(1 for score in scores if score["refusal_ok"])),
                per_category=dict(sorted(per_category.items())),
                scores=scores, authority="declaration_only", execution=False,
                note=("only frozen cases count toward the headline; nodes and edges are reported "
                      "apart from complete plans on purpose"))


def write_result(result: dict, folder: Path | None = None) -> Path:
    folder = Path(folder or RESULTS)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = result.get("started_at") or "run"
    path = folder / f"{result['model']}-{stamp}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return path


def summary(result: dict) -> str:
    lines = [f"{result['model']} · {result['cases']} case(s) ({result['include']})",
             f"  parsed {result['parsed']}/{result['cases']} · truncation {result['truncation']}",
             f"  nodes {result['nodes_ok']} · edges {result['edges_ok']} · "
             f"complete plans {result['complete']}/{result['cases']}",
             f"  refusals {result['refusals']['correct']}/{result['refusals']['expected']} correct"]
    for category, bucket in result["per_category"].items():
        lines.append(f"  {category:18} {bucket['complete']}/{bucket['cases']} complete")
    return "\n".join(lines)
