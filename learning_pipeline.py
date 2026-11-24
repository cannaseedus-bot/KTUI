"""Learning-u end to end: a candidate becomes a proposal, a verdict, and an evidence record - and stops there.

The chain the architecture describes, with every hop already tested separately, connected here so it is exercised
rather than merely declared:

    candidate (e.g. from Grams-u)
        -> learning-delta:v1        a proposal, authority "proposal"
        -> verified-delta:v1        only on PASS or FAIL
        -> evidence ledger append   admitted false, persistence "evidence_only"

STATUS: frozen (commit 7c9edd2, evidence 47c8cbd). The five hops, the authority separation and the delivery
semantics are exercised end to end and defended by guards. Two documented limits, neither of which justifies
reopening it without an operational requirement:

    duplicate detection is a linear scan of the ledger     correct at this scale, O(n) per delivery, and it must
                                                          never become a second source of truth if it is ever
                                                          replaced by an index
    a duplicate is defined by message identity            two independently generated candidates may describe
                                                          the same relationship and remain distinct evidence

Three things this refuses to do, because they are the boundaries the rest of the system relies on:

    it does not mutate the graph            graph_mutated is false and stays false
    it does not authorise admission         admitted is false at every hop
    it does not accept an unverified hop    a FAIL is recorded as a FAIL, and an invalid payload never reaches
                                            the ledger at all
"""
from __future__ import annotations

import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import evidence_record  # noqa: E402
import schema_bus  # noqa: E402

SCHEMA = "kuhul://learning/pipeline/v1"
PRODUCER = "micronaut://v1/learning"
VERIFIER = "micronaut://v1/ch_en"


def _existing(message_id: str) -> dict | None:
    """Has this exact verified message already been delivered to the ledger?"""
    for index, row in enumerate(evidence_record.load()):
        if str(row.get("request_id") or "") == message_id:
            return dict(sequence=index, request_id=message_id)
    return None


def run(candidate: dict, *, verdict: str, evidence: str = "", registry: dict | None = None,
        record: bool = True, path: Path | None = None, allow_redelivery: bool = False) -> dict:
    """One candidate through the whole chain, with every refusal reported rather than swallowed."""
    registry = registry or schema_bus.load()
    steps: list[dict] = []

    # The candidate has a contract of its own: a proposal built from a malformed candidate would be a
    # well-formed delta carrying nonsense, which is exactly the failure this hop prevents.
    candidate_problems = schema_bus.validate_payload(
        registry, "urn:kuhul:schema:semantic-candidate:v1", candidate)
    steps.append(dict(hop="candidate", ok=not candidate_problems, problems=candidate_problems))
    if candidate_problems:
        return dict(schema=SCHEMA, ok=False, refused="candidate_invalid", steps=steps,
                    problems=candidate_problems, admitted=False, execution=False, mutation=False,
                    note="a malformed candidate is refused before a proposal is built from it")

    delta = schema_bus.learning_delta(candidate)
    checked = schema_bus.validate(registry, delta)
    steps.append(dict(hop="delta", ok=checked["ok"], problems=checked["problems"]))
    if not checked["ok"]:
        return dict(schema=SCHEMA, ok=False, refused="delta_invalid", steps=steps,
                    admitted=False, execution=False, mutation=False,
                    note="an invalid proposal never reaches the ledger")

    routed = schema_bus.route(registry, delta, consumer="micronaut://v1/ch_en",
                              granted={"graph.relations.read"},
                              authenticated_producer=PRODUCER)
    steps.append(dict(hop="route", ok=routed["delivered"], refused=routed["refused"]))
    if not routed["delivered"]:
        return dict(schema=SCHEMA, ok=False, refused=routed["refused"], steps=steps,
                    admitted=False, execution=False, mutation=False)

    try:
        verified = schema_bus.verified_delta(delta, verdict=verdict, evidence=evidence)
    except ValueError as error:
        return dict(schema=SCHEMA, ok=False, refused="verdict_invalid", detail=str(error),
                    steps=steps, admitted=False, execution=False, mutation=False)
    steps.append(dict(hop="verified", ok=True, verdict=verified["payload"]["verdict"],
                      authority=verified["authority"]))

    if not record:
        return dict(schema=SCHEMA, ok=True, refused=None, steps=steps, delta=delta,
                    verdict=verified, evidence=None, admitted=False, execution=False,
                    mutation=False)

    # Duplicate delivery: the same verified message twice is not two independent pieces of evidence.
    message_id = f"delta:{delta.get('payload', {}).get('target')}:1"
    previous = _existing(message_id)
    if previous is not None and not allow_redelivery:
        steps.append(dict(hop="ledger", ok=False, refused="duplicate_delivery",
                          existing_sequence=previous["sequence"]))
        return dict(schema=SCHEMA, ok=False, refused="duplicate_delivery", steps=steps,
                    delta=delta, verdict=verified, existing=previous, evidence=None,
                    persisted=False, verification_ok=True, admitted=False, execution=False,
                    mutation=False,
                    note=("this verified message is already in the ledger; a second copy would look like "
                          "independent evidence, so it is refused (allow_redelivery records it as a "
                          "re-delivery instead)"))

    try:
        appended = schema_bus.append_verified_delta(delta, verified, producer=VERIFIER,
                                                    schema_version=1, path=path)
    except Exception as error:
        # A verification that cannot be persisted is not a persisted record, and must not read as one.
        steps.append(dict(hop="ledger", ok=False, refused="evidence_not_persisted",
                          error=f"{type(error).__name__}: {error}"[:160]))
        return dict(schema=SCHEMA, ok=False, refused="evidence_not_persisted", steps=steps,
                    delta=delta, verdict=verified, evidence=None, persisted=False,
                    verification_ok=True, admitted=False, execution=False, mutation=False,
                    detail=f"{type(error).__name__}: {error}"[:200],
                    note="the candidate was verified, but the evidence record was not written")

    delivery = "redelivery" if previous is not None else "first"
    steps.append(dict(hop="ledger", ok=True, sequence=appended["evidence"]["sequence"],
                      persistence=appended["record"]["persistence"], delivery=delivery,
                      original_sequence=(previous["sequence"] if previous else None)))
    return dict(schema=SCHEMA, ok=True, refused=None, steps=steps, delta=delta, verdict=verified,
                evidence=appended["record"], ledger=appended["evidence"],
                delivery=delivery, persisted=True, verification_ok=True,
                admitted=False, execution=False, mutation=False,
                note=("a verified proposal is recorded as evidence; nothing was admitted and no graph state "
                      "changed"))


def summary(result: dict) -> str:
    if not result.get("ok"):
        return (f"learning pipeline · REFUSED {result.get('refused')} "
                f"after {len(result.get('steps') or [])} hop(s)")
    evidence = result.get("evidence") or {}
    return (f"learning pipeline · ok · {len(result['steps'])} hop(s) · "
            f"verdict {evidence.get('verification', {}).get('verdict')} · "
            f"admitted {evidence.get('admitted')} · persistence {evidence.get('persistence')} · "
            f"graph_mutated {evidence.get('graph_mutated')}")


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Run one candidate through the learning chain.")
    parser.add_argument("--source", default="black dog")
    parser.add_argument("--target", default="large canine")
    parser.add_argument("--relation", default="semantic_similarity")
    parser.add_argument("--score", type=float, default=0.87)
    parser.add_argument("--verdict", default="PASS")
    args = parser.parse_args(argv)
    result = run(dict(source=args.source, target=args.target, relation=args.relation,
                      score=args.score), verdict=args.verdict)
    print(summary(result))
    print(json.dumps({key: result.get(key) for key in ("refused", "evidence", "ledger")},
                     indent=2, default=str)[:900])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
