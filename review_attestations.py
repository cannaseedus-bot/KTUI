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
    """The reviewer registry: role, independence and the public key that signs their attestations."""
    path = Path(path or (HOST_ROOT / "evaluation" / "reviewers.json"))
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, by_id={}, problems=[dict(code="reviewers", detail=str(error))])
    return dict(ok=True, by_id=record.get("reviewers") or {}, problems=[])


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
        if entry is None:
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
                verdict["reasons"].append(signature["reason"] or "signature_invalid")
        # Independence is a registry decision, not a signature property.
        verdict["independent"] = bool(entry and entry.get("independent")
                                      and attestation.get("decision") == "approved")
        verdict["ok"] = (not verdict["reasons"]) and attestation.get("decision") == "approved"
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
