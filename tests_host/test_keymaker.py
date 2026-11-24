"""M83: keymaker - create a cryptographic identity, never an authority.

The utility produces Ed25519 key pairs and SHA-256 digests, signs canonical payloads that the frozen attestation
verifier already accepts, and reports every result as `registered: false, authority: "unregistered"`. Generating a
key is not registering a reviewer and never grants independence.
"""
import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import keymaker  # noqa: E402
import review_attestations  # noqa: E402

HAS_CRYPTO = keymaker._crypto()


@unittest.skipUnless(HAS_CRYPTO, "the cryptography package is required")
class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.directory = Path(self.folder.name) / "identity"

    def tearDown(self):
        self.folder.cleanup()

    def test_a_generated_identity_is_unregistered_by_construction(self):
        identity = keymaker.generate_identity(self.directory, passphrase="pass")
        self.assertFalse(identity["registered"])
        self.assertEqual(identity["authority"], "unregistered")
        self.assertFalse(identity["independence"])
        self.assertTrue(identity["encrypted"])
        self.assertEqual(len(identity["fingerprint"]), 64)

    def test_the_private_key_is_encrypted_and_the_public_key_is_shareable(self):
        identity = keymaker.generate_identity(self.directory, passphrase="pass")
        private = Path(identity["private_key"]).read_bytes()
        self.assertIn(b"ENCRYPTED", private, "a passphrase was supplied, so the file must be encrypted")
        public = Path(identity["public_key_path"]).read_text(encoding="utf-8").strip()
        self.assertEqual(base64.b64decode(public), base64.b64decode(identity["public_key"]))

    def test_an_unencrypted_identity_says_so(self):
        identity = keymaker.generate_identity(self.directory)
        self.assertFalse(identity["encrypted"])
        self.assertNotIn(b"ENCRYPTED", Path(identity["private_key"]).read_bytes())

    def test_an_existing_identity_is_never_overwritten(self):
        keymaker.generate_identity(self.directory, passphrase="pass")
        with self.assertRaises(keymaker.KeymakerError):
            keymaker.generate_identity(self.directory, passphrase="other")

    def test_key_material_is_refused_inside_the_evaluation_corpus(self):
        with self.assertRaises(keymaker.KeymakerError):
            keymaker.generate_identity(ROOT / "evaluation" / "keys")

    def test_the_public_key_can_be_recovered_from_the_private_one(self):
        identity = keymaker.generate_identity(self.directory, passphrase="pass")
        recovered = keymaker.public_key_of(Path(identity["private_key"]), passphrase="pass")
        self.assertEqual(recovered, identity["public_key"])
        self.assertEqual(keymaker.fingerprint(recovered), identity["fingerprint"])

    def test_a_wrong_passphrase_cannot_open_the_key(self):
        identity = keymaker.generate_identity(self.directory, passphrase="pass")
        with self.assertRaises(keymaker.KeymakerError):
            keymaker.public_key_of(Path(identity["private_key"]), passphrase="wrong")

    def test_the_fingerprint_is_a_digest_of_the_key_bytes(self):
        import hashlib

        identity = keymaker.generate_identity(self.directory, passphrase="pass")
        expected = hashlib.sha256(base64.b64decode(identity["public_key"])).hexdigest()
        self.assertEqual(keymaker.fingerprint(identity["public_key"]), expected)
        self.assertEqual(identity["fingerprint"], expected,
                         "the fingerprint identifies the key; it proves nothing about who holds it")


@unittest.skipUnless(HAS_CRYPTO, "the cryptography package is required")
class SignatureTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.identity = keymaker.generate_identity(Path(self.folder.name) / "k", passphrase="pass")
        self.private = Path(self.identity["private_key"])

    def tearDown(self):
        self.folder.cleanup()

    def test_a_keymaker_signature_is_accepted_by_the_frozen_verifier(self):
        attestation = dict(schema=review_attestations.SCHEMA, case_id="pair-01",
                           expected_graph_sha256="d" * 64,
                           contract="kuhul://operators/v1", reviewer="reviewer://someone",
                           decision="approved")
        signature = keymaker.sign(review_attestations.canonical(attestation), self.private,
                                  passphrase="pass")
        signed = dict(attestation, signature_algorithm="Ed25519", signature=signature)
        self.assertTrue(review_attestations.verify(signed, self.identity["public_key"])["ok"],
                        "one signature format, not a second one")

    def test_a_signature_verifies_only_the_exact_bytes(self):
        payload = b'{"a":1}'
        signature = keymaker.sign(payload, self.private, passphrase="pass")
        self.assertTrue(keymaker.verify(payload, signature, self.identity["public_key"]))
        self.assertFalse(keymaker.verify(payload + b" ", signature, self.identity["public_key"]))

    def test_a_signature_from_another_key_does_not_verify(self):
        other = keymaker.generate_identity(Path(self.folder.name) / "other", passphrase="pass")
        signature = keymaker.sign(b"payload", self.private, passphrase="pass")
        self.assertFalse(keymaker.verify(b"payload", signature, other["public_key"]))

    def test_an_invalid_public_key_is_refused_not_returned_false(self):
        with self.assertRaises(keymaker.KeymakerError):
            keymaker.verify(b"payload", "AAAA", "not-a-key")

    def test_a_digest_matches_the_artifact(self):
        artifact = Path(self.folder.name) / "artifact.json"
        artifact.write_text(json.dumps({"a": 1}), encoding="utf-8")
        self.assertEqual(keymaker.digest(artifact), keymaker.digest(artifact))
        self.assertEqual(len(keymaker.digest(artifact)), 64)


if __name__ == "__main__":
    unittest.main()
