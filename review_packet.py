"""Build the packet a first reviewer signs - expectations only, never a model's answer.

The review cycle is deliberately small and varied:

    pair-01        operator nodes and ordering
    chain-01       FOLD containment and ACCUMULATE semantics
    authority-01   refusal and execution-authority boundary
    srai-01        redirect and wildcard correctness
    rest-01        caller scope and target authorization

The packet carries, per case: the input, the expected operator graph, the contract version, the expectation
digest and an **unsigned** attestation template. It carries no model output, no score, and no private key -
a reviewer who saw a model's answer would be grading agreement, not the expectation.

The reviewer signs with their own key; the harness only ever verifies.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
for _candidate in (str(HOST_ROOT / "kuhul-phase-engine-v0.1.0" / "core"), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import evaluation_harness  # noqa: E402
import review_attestations  # noqa: E402

PACKET = HOST_ROOT / "evaluation" / "review-packet"
SCHEMA = "kuhul://evaluation/review-packet/v1"
CASES = ("pair-01", "chain-01", "authority-01", "srai-01", "rest-01")
CHECK_FOCUS = {
    "pair-01": "operator nodes, their count, and their order",
    "chain-01": "FOLD owns the accumulation; ACCUMULATE is nested, never a substitute",
    "authority-01": "the expectation is a refusal, and no execution authority is implied",
    "srai-01": "the redirect target and the wildcard substitution",
    "rest-01": "caller scope and the authorized target",
}


def build(cases=CASES, *, output: Path | None = None) -> dict:
    """Write the packet: one JSON file of expectations and one markdown brief."""
    corpus = evaluation_harness.load()
    if not corpus["ok"]:
        raise RuntimeError(f"the corpus does not load: {corpus['problems']}")
    records, missing = [], []
    for case_id in cases:
        case = corpus["by_id"].get(case_id)
        if case is None:
            missing.append(case_id)
            continue
        expect = case.get("expect") or {}
        records.append(dict(
            case_id=case_id, category=case.get("category"), contract=case.get("contract"),
            input=case.get("input"),
            expected_phase=expect.get("phase"),
            expected_graph=expect.get("graph"),
            authorized_targets=list(expect.get("targets") or []),
            expected_refusal=expect.get("refusal"),
            unknown_facts=bool(expect.get("unknown_facts")),
            expected_graph_sha256=case.get("expected_graph_sha256"),
            check_focus=CHECK_FOCUS.get(case_id, "as declared"),
            attestation_template=dict(
                schema=review_attestations.SCHEMA, case_id=case_id,
                expected_graph_sha256=case.get("expected_graph_sha256"),
                contract=case.get("contract"),
                reviewer="REPLACE-WITH-YOUR-REVIEWER-ID",
                decision="approved|rejected",
                signature_algorithm="Ed25519", signature="SIGN-WITH-YOUR-OWN-KEY")))
    packet = dict(schema=SCHEMA, authority="declaration_only",
                  cases=records, missing=missing,
                  reviewer_instructions=dict(
                      read="inspect the input, the expected graph, the contract and the authorized targets",
                      do_not_read="any model output, score or proposal - this packet contains none",
                      sign="sign the canonical payload of each attestation with your own Ed25519 key",
                      submit="send the signed attestations; the harness verifies, it never signs",
                      register=("a public key in reviewers.json makes you a recognized signer; independence "
                                "needs a separate onboarding record authorized by the project owner")),
                  onboarding_template=dict(
                      reviewer="REPLACE-WITH-YOUR-REVIEWER-ID",
                      public_key="BASE64-RAW-ED25519-PUBLIC-KEY",
                      onboarding=dict(authorized_by="human://project-owner",
                                      authorized_at="REPLACE-WITH-DATE",
                                      independent=True,
                                      declaration=("I did not author these cases and derived my judgement "
                                                   "from the expectations alone"))),
                  status=review_attestations.status(corpus)["counts"])
    if output is not None:
        write(packet, Path(output))
    return packet


def write(packet: dict, folder: Path | None = None) -> list[str]:
    folder = Path(folder or PACKET)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    data = folder / "packet.json"
    data.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    written.append(str(data))
    brief = [f"# Independent review packet ({packet['schema']})", "",
             "Five frozen expectations, chosen for variety. Review each against its input, expected graph,",
             "contract and authorized targets. No model output or score is included, by design.", "",
             f"Current counts: {packet['status']}", ""]
    for case in packet["cases"]:
        brief += [f"## {case['case_id']} — {case['category']}", "",
                  f"- **Input**: {case['input']}",
                  f"- **Expected phase**: {case['expected_phase']}",
                  f"- **Contract**: {case['contract']}",
                  f"- **Authorized targets**: {', '.join(case['authorized_targets']) or '(none)'}",
                  f"- **Expected refusal**: {case['expected_refusal'] or 'none'}",
                  f"- **Unknown facts**: {case['unknown_facts']}",
                  f"- **Check focus**: {case['check_focus']}",
                  f"- **Expectation digest**: `{case['expected_graph_sha256']}`", "",
                  "```json",
                  json.dumps(case["expected_graph"], indent=2),
                  "```", ""]
    brief += ["## How to sign", "",
              "Sign the canonical payload (`schema`, `case_id`, `expected_graph_sha256`, `contract`,",
              "`reviewer`, `decision`) with your own Ed25519 key. The harness verifies against the public key",
              "registered for you and never signs on your behalf.", ""]
    markdown = folder / "REVIEW.md"
    markdown.write_text("\n".join(brief) + "\n", encoding="utf-8")
    written.append(str(markdown))
    return written


def summary(packet: dict) -> str:
    lines = [f"review packet · {len(packet['cases'])} case(s) · missing {packet['missing'] or 'none'}",
             f"  current counts: {packet['status']}"]
    for case in packet["cases"]:
        lines.append(f"  {case['case_id']:14} {case['category']:16} phase {case['expected_phase']:6} "
                     f"targets {', '.join(case['authorized_targets']) or '(none)'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build the first-review packet from the frozen corpus.")
    parser.add_argument("--out", default=str(PACKET))
    args = parser.parse_args(argv)
    packet = build()
    written = write(packet, Path(args.out))
    print(summary(packet))
    for path in written:
        print(f"written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
