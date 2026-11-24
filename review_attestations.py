"""Signed review attestations: a review counts when a key proves it, not when a field claims it.

The distinction the review drew, and the reason this module exists:

    a field claiming `method: "independent"`   establishes an identity *claim*
    a signature over the exact case content    establishes key possession and payload integrity

So an attestation is a separate artifact, signed by the reviewer, never by the harness on their behalf:

    {"schema": "kuhul://evaluation/review/v1", "case_id": ..., "contract": ...,
     "expected_graph_sha256": ..., "reviewer": ..., "decision": "approved",
     "signature_algorithm": "Ed25519", "signature": "<base64 over the canonical payload>"}

The canonical payload covers the schema version, the case id, the expectation digest, the contract and the
reviewer, so an approval cannot be copied onto a different case or a rewritten expectation. A signature
proves key possession; it does **not** prove human independence - that stays an onboarding decision in
`reviewers.json`, which is why an author key signing every case still yields zero benchmark-eligible cases.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

SCHEMA = "kuhul://evaluation/review/v1"
DECISIONS = ("approved", "rejected")
ATTESTATIONS = HOST_ROOT / "evaluation" / "review-attestations.jsonl"
PAYLOAD_FIELDS = ("schema", "case_id", "expected_graph_sha256", "contract", "reviewer", "decision")


def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: F401
            Ed25519PrivateKey, Ed25519PublicKey)
        return True
    except ImportError:
        return False


def canonical(attestation: dict) -> bytes:
    """The bytes that get signed: the payload fields, canonically ordered, nothing else."""
    payload = {field: attestation.get(field) for field in PAYLOAD_FIELDS}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


# -- keys ---------------------------------------------------------------------------------------------
def generate_keypair(private_path: Path, *, overwrite: bool = False) -> dict:
    """Create an Ed25519 key pair. The private key is the reviewer's; the public half is registered."""
    if not _crypto():
        raise RuntimeError("the cryptography package is required to sign attestations")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_path = Path(private_path)
    if private_path.exists() and not overwrite:
        raise FileExistsError(f"{private_path} already exists; refusing to replace a signing key")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    private_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()))
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    return dict(private_path=str(private_path),
                public_key=base64.b64encode(public).decode("ascii"))


def sign(attestation: dict, private_path: Path) -> dict:
    """Sign one attestation. The reviewer signs; the harness only checks."""
    if not _crypto():
        raise RuntimeError("the cryptography package is required to sign attestations")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if attestation.get("decision") not in DECISIONS:
        raise ValueError(f"decision {attestation.get('decision')!r} is not one of {DECISIONS}")
    key = serialization.load_pem_private_key(Path(private_path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("that is not an Ed25519 private key")
    signature = key.sign(canonical(attestation))
    return dict(attestation, signature_algorithm="Ed25519",
                signature=base64.b64encode(signature).decode("ascii"))


def verify(attestation: dict, public_key: str) -> dict:
    """Check one attestation against a registered public key (raw, base64)."""
    if not _crypto():
        return dict(ok=False, reason="the cryptography package is not installed")
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if attestation.get("signature_algorithm") != "Ed25519":
        return dict(ok=False, reason=f"unsupported algorithm {attestation.get('signature_algorithm')!r}")
    if attestation.get("decision") not in DECISIONS:
        return dict(ok=False, reason=f"decision {attestation.get('decision')!r}")
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(str(public_key or "")))
    except Exception:
        return dict(ok=False, reason="the registered public key is not a valid Ed25519 key")
    try:
        key.verify(base64.b64decode(str(attestation.get("signature") or "")), canonical(attestation))
    except (InvalidSignature, ValueError):
        return dict(ok=False, reason="the signature does not match the payload and this key")
    return dict(ok=True, reason=None)


# -- loading and checking a file of attestations ------------------------------------------------------
def load(path: Path | None = None) -> list[dict]:
    path = Path(path or ATTESTATIONS)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def registry(path: Path | None = None) -> dict:
    """The reviewer registry: role, onboarding, independence and the public key that signs reviews.

    A registry that cannot be read is a *configuration* failure, not a policy decision: the caller must be
    able to tell `reviewer_registry_unavailable` from `reviewer_not_registered`.
    """
    path = Path(path or (HOST_ROOT / "evaluation" / "reviewers.json"))
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, available=False, by_id={}, path=str(path),
                    problems=[dict(code="reviewer_registry_unavailable", detail=f"{path}: {error}")])
    reviewers = record.get("reviewers")
    if not isinstance(reviewers, dict):
        return dict(ok=False, available=False, by_id={}, path=str(path),
                    problems=[dict(code="reviewer_registry_unavailable",
                                   detail=f"{path}: no reviewers object")])
    return dict(ok=True, available=True, by_id=reviewers, path=str(path), problems=[])


def independence(entry: dict) -> dict:
    """Independence needs an authorized onboarding record, not a flag someone edited into the file."""
    onboarding = (entry or {}).get("onboarding") or {}
    if not onboarding:
        return dict(independent=False, reason="onboarding_missing")
    if str(onboarding.get("authorized_by") or "") == str((entry or {}).get("reviewer") or ""):
        return dict(independent=False, reason="self_onboarded")
    if onboarding.get("independent") is not True:
        return dict(independent=False, reason="onboarding_not_independent")
    if not str(onboarding.get("authorized_by") or "").strip():
        return dict(independent=False, reason="onboarding_unauthorized")
    return dict(independent=True, reason=None,
                authorized_by=str(onboarding["authorized_by"]),
                authorized_at=onboarding.get("authorized_at"))


def check(corpus: dict, attestations: list[dict], registry_record: dict | None = None) -> dict:
    """Verify each attestation against the corpus and the registry; only verified ones count."""
    registry_record = registry_record or registry()
    results = []
    for attestation in attestations:
        case_id = str(attestation.get("case_id") or "")
        case = (corpus.get("by_id") or {}).get(case_id)
        reviewer = str(attestation.get("reviewer") or "")
        entry = (registry_record.get("by_id") or {}).get(reviewer)
        verdict = dict(case_id=case_id, reviewer=reviewer,
                       decision=attestation.get("decision"), ok=False, reasons=[])
        if case is None:
            verdict["reasons"].append("case_not_in_corpus")
        if registry_record.get("available") is False:
            verdict["reasons"].append("reviewer_registry_unavailable")
        elif entry is None:
            verdict["reasons"].append("reviewer_not_registered")
        if attestation.get("schema") != SCHEMA:
            verdict["reasons"].append("schema_mismatch")
        if case is not None and attestation.get("expected_graph_sha256") != case.get(
                "expected_graph_sha256"):
            verdict["reasons"].append("digest_mismatch")
        if case is not None and attestation.get("contract") != case.get("contract"):
            verdict["reasons"].append("contract_mismatch")
        if entry is not None:
            signature = verify(attestation, entry.get("public_key") or "")
            if not signature["ok"]:
                verdict["reasons"].append("signature_invalid")
                verdict["signature_reason"] = signature.get("reason")
        # Independence is an onboarding decision, not a signature property and not a file flag.
        standing = independence(entry or {})
        # Independence is separate from verification: a valid author signature is *verified* evidence and
        # still not benchmark-eligible. It must not turn into a refusal.
        eligibility = independence(entry or {})
        verdict["independence_reason"] = eligibility["reason"]
        verdict["independent"] = bool(standing["independent"]
                                      and attestation.get("decision") == "approved"
                                      and not verdict["reasons"])
        verdict["ok"] = (not verdict["reasons"]) and attestation.get("decision") == "approved"
        verdict["status"] = ("verified_independent" if verdict["independent"] else
                             "verified_not_independent" if verdict["ok"] else
                             "rejected_decision" if not verdict["reasons"] else "refused")
        results.append(verdict)
    verified = [verdict for verdict in results if verdict["ok"]]
    independent = [verdict for verdict in verified if verdict["independent"]]
    rejected = [verdict for verdict in results if verdict["decision"] == "rejected" and not verdict["reasons"]]
    return dict(schema=SCHEMA, attestations=len(results), verified=len(verified),
                independent=len(independent),
                independently_reviewed_cases=sorted({verdict["case_id"] for verdict in independent}),
                rejected=sorted({verdict["case_id"] for verdict in rejected}),
                verdicts=results, authority="declaration_only")


def summary(report: dict) -> str:
    lines = [f"review attestations · {report['attestations']} present · {report['verified']} verified · "
             f"{report['independent']} independent"]
    for verdict in report["verdicts"]:
        state = "verified" if verdict["ok"] else "REFUSED"
        independence = "independent" if verdict.get("independent") else "not independent"
        lines.append(f"  {verdict['case_id']:14} {verdict['reviewer']:28} {verdict['decision']:9} "
                     f"{state} · {independence}"
                     + (f" · {', '.join(verdict['reasons'])}" if verdict["reasons"] else ""))
    if report["independently_reviewed_cases"]:
        lines.append(f"  independently reviewed: {', '.join(report['independently_reviewed_cases'])}")
    else:
        lines.append("  independently reviewed: none - no registered reviewer is marked independent")
    return "\n".join(lines)

def status(corpus: dict, *, attestation_path: Path | None = None,
           registry_record: dict | None = None) -> dict:
    """The three counts the review cycle needs, kept apart because they mean different things."""
    registry_record = registry_record or registry()
    checked = check(corpus, load(attestation_path), registry_record)
    frozen = [case["id"] for case in corpus.get("cases") or []
              if case.get("review_status") == "frozen"]
    approved = set(checked["independently_reviewed_cases"])
    rejected = set(checked.get("rejected") or [])
    eligible = [case_id for case_id in frozen if case_id in approved and case_id not in rejected]
    return dict(schema="kuhul://evaluation/review-status/v1",
                registry_available=bool(registry_record.get("available")),
                verified_attestations=checked["verified"],
                independently_approved_cases=sorted(approved),
                benchmark_eligible_cases=eligible,
                frozen_cases=len(frozen),
                counts=dict(verified=checked["verified"],
                            independently_approved=len(approved),
                            benchmark_eligible=len(eligible)),
                verdicts=checked["verdicts"],
                statement=_statement(len(approved), len(frozen)),
                authority="declaration_only", execution=False)


def _statement(approved: int, frozen: int) -> str:
    if approved == 0:
        return (f"these {frozen} expectations are frozen and no case is independently approved, so the "
                f"results are regression evidence, not validated accuracy")
    if approved < frozen:
        return (f"{approved} of {frozen} expectations are independently approved; only those are "
                f"benchmark-eligible")
    return f"all {frozen} expectations are independently approved"

