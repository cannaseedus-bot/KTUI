"""K'UHUL Keymaker: create a cryptographic identity, and never assign one an authority.

    generate      Ed25519 private/public key pair, private half encrypted with a passphrase
    sign          Ed25519 signature over the canonical attestation payload
    verify        signature check against a public key
    fingerprint   SHA-256 of the raw public key
    digest        SHA-256 of an artifact

Two rules this utility enforces, both learned the hard way in this repository:

    generating a key does not register a reviewer, and never grants independence   every result says so
    a private key never lands in `evaluation/`                                     a refusal, not a convention

The reviewer runs this on their own machine. This project must not generate or hold their private key; an author
or service identity can be generated locally, and it is still `unregistered` until the registry and the onboarding
policy say otherwise.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
SCHEMA = "kuhul://keymaker/v1"
ALGORITHM = "Ed25519"
DIGEST = "SHA-256"


class KeymakerError(ValueError):
    """An operation the utility refuses to perform."""


def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: F401
            Ed25519PrivateKey, Ed25519PublicKey)
        return True
    except ImportError:
        return False


def _guard_destination(directory: Path) -> Path:
    """Key material must never sit beside the cases it could be used to approve."""
    directory = Path(directory).resolve()
    forbidden = (HOST_ROOT / "evaluation").resolve()
    if directory == forbidden or forbidden in directory.parents:
        raise KeymakerError("refusing to write key material under evaluation/")
    return directory


def fingerprint(public_key: str) -> str:
    """SHA-256 over the raw public key: an identifier, not a proof of authorship."""
    return hashlib.sha256(base64.b64decode(str(public_key or ""))).hexdigest()


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate_identity(directory: Path, *, passphrase: str | None = None,
                      overwrite: bool = False) -> dict:
    """Create a key pair. The private half is encrypted whenever a passphrase is supplied."""
    if not _crypto():
        raise KeymakerError("the cryptography package is required")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    directory = _guard_destination(Path(directory))
    private_path = directory / "ed25519-private.pem"
    public_path = directory / "ed25519-public.pem"
    if (private_path.exists() or public_path.exists()) and not overwrite:
        raise KeymakerError(f"an identity already exists in {directory}; refusing to overwrite")
    directory.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    if passphrase:
        encryption = serialization.BestAvailableEncryption(passphrase.encode("utf-8"))
    else:
        encryption = serialization.NoEncryption()
    private_bytes = key.private_bytes(encoding=serialization.Encoding.PEM,
                                      format=serialization.PrivateFormat.PKCS8,
                                      encryption_algorithm=encryption)
    public_raw = key.public_key().public_bytes(encoding=serialization.Encoding.Raw,
                                               format=serialization.PublicFormat.Raw)
    # Write the private half first, to a temporary name, so a crash cannot leave a half-written key.
    temp = private_path.with_suffix(".pem.tmp")
    temp.write_bytes(private_bytes)
    if os.name == "posix":
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
    temp.replace(private_path)
    public_path.write_text(base64.b64encode(public_raw).decode("ascii") + "\n", encoding="utf-8")
    return dict(schema=SCHEMA, algorithm=ALGORITHM, digest=DIGEST,
                private_key=str(private_path), public_key_path=str(public_path),
                public_key=base64.b64encode(public_raw).decode("ascii"),
                fingerprint=fingerprint(base64.b64encode(public_raw).decode("ascii")),
                encrypted=bool(passphrase),
                registered=False, independence=False, authority="unregistered",
                note=("a generated key is an identity, not an authority: registration and independence are "
                       "decisions made by the reviewer registry and the onboarding policy"))


def public_key_of(private_path: Path, *, passphrase: str | None = None) -> str:
    if not _crypto():
        raise KeymakerError("the cryptography package is required")
    from cryptography.hazmat.primitives import serialization

    try:
        key = serialization.load_pem_private_key(Path(private_path).read_bytes(),
                                                 password=passphrase.encode("utf-8") if passphrase else None)
    except (TypeError, ValueError) as error:
        raise KeymakerError(f"the private key could not be opened: {error}") from error
    raw = key.public_key().public_bytes(encoding=serialization.Encoding.Raw,
                                        format=serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def sign(payload: bytes, private_path: Path, *, passphrase: str | None = None) -> str:
    if not _crypto():
        raise KeymakerError("the cryptography package is required")
    from cryptography.hazmat.primitives import serialization

    try:
        key = serialization.load_pem_private_key(Path(private_path).read_bytes(),
                                                 password=passphrase.encode("utf-8") if passphrase else None)
    except (TypeError, ValueError) as error:
        raise KeymakerError(f"the private key could not be opened: {error}") from error
    return base64.b64encode(key.sign(payload)).decode("ascii")


def verify(payload: bytes, signature: str, public_key: str) -> bool:
    """True when this public key signed these exact bytes. It proves key possession, nothing more."""
    if not _crypto():
        raise KeymakerError("the cryptography package is required")
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(str(public_key or "")))
    except Exception as error:
        raise KeymakerError(f"the public key is not a valid Ed25519 key: {error}") from error
    try:
        key.verify(base64.b64decode(str(signature or "")), payload)
    except (InvalidSignature, ValueError):
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    import argparse
    import getpass

    parser = argparse.ArgumentParser(description="K'UHUL keymaker: identities, signatures, digests.")
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="create an Ed25519 key pair")
    generate.add_argument("--dir", default=str(HOST_ROOT / "logs" / "keys" / "identity"))
    generate.add_argument("--no-passphrase", action="store_true",
                          help="write an unencrypted private key (development only)")

    print_key = sub.add_parser("fingerprint", help="SHA-256 of a public key")
    print_key.add_argument("--public", required=True, help="base64 raw public key, or a path to it")

    sign_parser = sub.add_parser("sign", help="sign a file")
    sign_parser.add_argument("--key", required=True)
    sign_parser.add_argument("--file", required=True)

    verify_parser = sub.add_parser("verify", help="verify a signature over a file")
    verify_parser.add_argument("--public", required=True)
    verify_parser.add_argument("--file", required=True)
    verify_parser.add_argument("--signature", required=True)

    digest_parser = sub.add_parser("digest", help="SHA-256 of a file")
    digest_parser.add_argument("--file", required=True)

    args = parser.parse_args(argv)
    if args.command == "generate":
        passphrase = None
        if not args.no_passphrase:
            first = getpass.getpass("Private-key passphrase: ")
            if first != getpass.getpass("Repeat passphrase: "):
                print("passphrases do not match; nothing written")
                return 2
            passphrase = first or None
        try:
            result = generate_identity(Path(args.dir), passphrase=passphrase)
        except (KeymakerError, FileExistsError) as error:
            print(f"refused: {error}")
            return 1
        print(json.dumps({key: result[key] for key in
                          ("public_key", "fingerprint", "private_key", "encrypted", "registered",
                           "authority")}, indent=2))
        print("share only the public key; keep the private half on your own machine")
        return 0
    if args.command == "fingerprint":
        candidate = Path(args.public)
        value = candidate.read_text(encoding="utf-8").strip() if candidate.is_file() else args.public
        print(fingerprint(value))
        return 0
    if args.command == "digest":
        print(digest(Path(args.file)))
        return 0
    if args.command == "sign":
        passphrase = getpass.getpass("Private-key passphrase (blank if none): ") or None
        print(sign(Path(args.file).read_bytes(), Path(args.key), passphrase=passphrase))
        return 0
    candidate = Path(args.public)
    value = candidate.read_text(encoding="utf-8").strip() if candidate.is_file() else args.public
    ok = verify(Path(args.file).read_bytes(), args.signature, value)
    print("valid" if ok else "invalid")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
