"""Optional tamper-evident audit ledger for the host: append-only, hash-chained, signed.

What this is: a single-authority ledger of host events (gate reports, ledger mirrors, whatever a
caller appends) in which every record carries `sequence`, `previous_hash`, `content_hash` and - when
a key is available - an Ed25519 signature over the canonical form. Editing a record, deleting one, or
reordering them breaks the chain at a named index.

What this is NOT: a distributed ledger. There is no consensus, no network validation and no
double-spend prevention, because there is one authority (this host). The GML document `ledger.gml`
describes the record shape and grants nothing; admission still belongs to the host.

Canonical form is `json.dumps(record, sort_keys=True, separators=(",", ":"))` over UTF-8. Payloads may
hold strings, integers, booleans, nulls, lists and dicts; floats are refused because they make
byte-identical serialization a portability question rather than a guarantee.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
LEDGER_PATH = APP_ROOT / "logs" / "audit-ledger.jsonl"
SCHEMA_PATH = APP_ROOT / "ledger.gml"
KEY_ENV = "KNUMATIC_LEDGER_KEY"
DEFAULT_KEY = APP_ROOT / ".ledger-key.pem"
SCHEMA_ID = "gml-crypto-ledger/1"
REQUIRED_FIELDS = ("sequence", "previous_hash", "content_hash", "kind")
GENESIS = "sha256:" + "0" * 64
SCALARS = (str, int, bool, type(None))


class LedgerError(ValueError):
    """A record that would break the chain, or a chain that no longer verifies."""


def _refuse_floats(value, where="payload"):
    if isinstance(value, float):
        raise LedgerError(f"{where} contains a float; use an int or a string so serialization is byte-stable")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise LedgerError(f"{where} has a non-string key {key!r}")
            _refuse_floats(item, f"{where}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _refuse_floats(item, f"{where}[{index}]")
    elif not isinstance(value, SCALARS):
        raise LedgerError(f"{where} holds {type(value).__name__}, which has no canonical form")


def canonical(record: dict) -> bytes:
    """Deterministic bytes for a record: key order and formatting cannot vary."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# Fields that are not part of what a record *says*: the digest itself and the authentication fields.
# They are excluded from both the digest and the signature, so a record's hash covers its content only.
NON_BODY_FIELDS = ("content_hash", "signature", "public_key")


def body_of(record: dict) -> dict:
    return {key: value for key, value in record.items() if key not in NON_BODY_FIELDS}


def content_hash(record: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical(body_of(record))).hexdigest()


# -- keys and signatures ---------------------------------------------------------------------------
def _ed25519():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: F401
        from cryptography.hazmat.primitives import serialization  # noqa: F401
    except Exception:
        return None
    return True


def available() -> dict:
    return dict(signatures=_ed25519() is not None,
                reason=None if _ed25519() else "the cryptography package is not installed")


def load_key(path: Path | None = None, *, create: bool = False):
    """An Ed25519 private key, or None. Creating one writes a PEM the caller owns."""
    if not _ed25519():
        return None
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    target = Path(path or os.environ.get(KEY_ENV) or DEFAULT_KEY)
    if target.is_file():
        return serialization.load_pem_private_key(target.read_bytes(), password=None)
    if not create:
        return None
    key = Ed25519PrivateKey.generate()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()))
    return key


def public_bytes(key) -> str:
    from cryptography.hazmat.primitives import serialization
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw).hex()


def sign(record: dict, key) -> str:
    """Ed25519 over the canonical record. Unsigned ledgers are allowed and say so."""
    return "ed25519:" + key.sign(canonical(body_of(record))).hex()


def verify_signature(record: dict, signature: str, public_hex: str) -> bool:
    if not _ed25519() or not signature or not public_hex:
        return False
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex))
        key.verify(bytes.fromhex(signature.split(":", 1)[-1]), canonical(body_of(record)))
        return True
    except (InvalidSignature, ValueError):
        return False


# -- the chain -------------------------------------------------------------------------------------
def schema_fields(path: Path = SCHEMA_PATH) -> tuple[tuple[str, ...], str]:
    """Field names from the GML document. The document describes the record; this module enforces it."""
    try:
        try:  # the package's own parser is tracked, unlike a loose gml2.py in the checkout root
            import phases
            gml2 = phases.core_module("gml2")
        except Exception:
            import gml2
        document = gml2.parse(Path(path).read_text(encoding="utf-8"))
        fields = []
        for entry in getattr(document, "entries", []):
            if getattr(entry, "name", "") != "field":
                continue
            name = next((item.value for item in entry.value.entries if item.name == "name"), None)
            if isinstance(name, str):
                fields.append(name)
        return tuple(fields) or REQUIRED_FIELDS, "ledger.gml"
    except Exception:
        return REQUIRED_FIELDS, "built-in defaults (gml2 or ledger.gml unavailable)"


def _lines(path: Path) -> list[str]:
    if not Path(path).is_file():
        return []
    return [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def head(path: Path = LEDGER_PATH) -> dict | None:
    lines = _lines(path)
    return json.loads(lines[-1]) if lines else None


def append(entry: dict, path: Path = LEDGER_PATH, *, key_path: Path | None = None,
           create_key: bool = False, verify_first: bool = True) -> dict:
    """Append one record, refusing anything that would break the chain."""
    path = Path(path)
    if verify_first and _lines(path):
        report = verify(path)
        if not report["ok"]:
            raise LedgerError(f"refusing to append: the ledger does not verify ({report['reasons'][0]})")
    fields, _ = schema_fields()
    previous = head(path)
    sequence = (previous or {}).get("sequence", -1) + 1
    body = {
        "sequence": sequence,
        "previous_hash": (previous or {}).get("content_hash", GENESIS),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": str(entry.get("kind") or "event"),
    }
    payload = entry.get("payload") or {}
    _refuse_floats(payload)
    body["payload"] = payload
    record = dict(body)
    record["content_hash"] = content_hash(record)
    # Signing is explicit: a key on disk does not silently change what the ledger records. The env
    # var counts as explicit configuration; the mere existence of .ledger-key.pem does not.
    wants_signature = bool(key_path or create_key or os.environ.get(KEY_ENV))
    key = load_key(key_path, create=create_key) if wants_signature else None
    if key is not None:
        record["signature"] = sign(record, key)
        record["public_key"] = public_bytes(key)
    missing = [name for name in REQUIRED_FIELDS if name not in record]
    if missing:
        raise LedgerError(f"record is missing {missing} (declared in {', '.join(fields)})")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def verify(path: Path = LEDGER_PATH, *, public_hex: str | None = None) -> dict:
    """Walk the chain: sequence order, links, content hashes, signatures."""
    lines = _lines(path)
    reasons: list[dict] = []
    previous_hash = GENESIS
    signed = 0
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            reasons.append(dict(code="unparseable", index=index, detail=str(error)))
            break
        if record.get("sequence") != index:
            reasons.append(dict(code="sequence_gap", index=index,
                                detail=f"sequence {record.get('sequence')!r} at line {index}"))
        if record.get("previous_hash") != previous_hash:
            reasons.append(dict(code="broken_link", index=index,
                                detail=f"previous_hash {record.get('previous_hash')!r} != {previous_hash!r}"))
        expected = content_hash(record)
        if record.get("content_hash") != expected:
            reasons.append(dict(code="content_mismatch", index=index,
                                detail=f"content_hash {record.get('content_hash')!r} != {expected!r}"))
        signature = record.get("signature")
        if signature:
            signed += 1
            key = public_hex or record.get("public_key")
            if not verify_signature(record, signature, key or ""):
                reasons.append(dict(code="bad_signature", index=index,
                                    detail="signature does not verify over the canonical record"))
        previous_hash = record.get("content_hash", "")
    return dict(ok=not reasons, entries=len(lines), signed=signed,
                unsigned=len(lines) - signed, reasons=reasons,
                head=(json.loads(lines[-1]).get("content_hash") if lines else GENESIS),
                algorithm="ed25519+sha256" if signed else "sha256 only")


def record_gate_report(report: dict, path: Path = LEDGER_PATH, **kwargs) -> dict:
    """Append a host-gate verdict. A recorded verdict authorizes nothing - it is audit history."""
    verdict = report.get("verdict") or {}
    payload = {
        "tested_commit": verdict.get("tested_commit"),
        "evidence_satisfied": bool(verdict.get("evidence_satisfied")),
        "merge_authorized": False,
        "authority": verdict.get("authority"),
        "ledgers": {name: item.get("state") for name, item in (verdict.get("ledgers") or {}).items()},
        "comparability": [item.get("code") for item in (report.get("comparability") or {}).get("informational", [])],
    }
    return append(dict(kind="host-gate-report", payload=payload), path, **kwargs)
