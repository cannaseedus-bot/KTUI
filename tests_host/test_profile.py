"""M84: a local profile is configuration, not an authority, and never a secret store.

The review's shape without OAuth is right for a one-machine bot: a profile file per user, read by AIML/SRAI on
request. What must not come with it is a second place where permissions or secrets live, so a profile that declares
capabilities, tokens or a key is refused at load and at save.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import profile  # noqa: E402

GOOD = dict(display_name="Bill", locale="en-GB", preferences={"verbosity": "short"},
            bindings={"srai://user/topic": "dog"})


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original = os.environ.get("AIML_PROFILES")
        os.environ["AIML_PROFILES"] = self.folder.name

    def tearDown(self):
        if self.original is None:
            os.environ.pop("AIML_PROFILES", None)
        else:
            os.environ["AIML_PROFILES"] = self.original
        self.folder.cleanup()

    def test_a_profile_round_trips_as_configuration(self):
        self.assertTrue(profile.save("42", GOOD)["saved"])
        loaded = profile.load("42")
        self.assertTrue(loaded["ok"])
        self.assertTrue(loaded["exists"])
        self.assertEqual(loaded["profile"]["display_name"], "Bill")
        self.assertEqual(loaded["authority"], "declaration_only")

    def test_a_missing_profile_is_empty_not_an_error(self):
        loaded = profile.load("nobody")
        self.assertTrue(loaded["ok"])
        self.assertFalse(loaded["exists"])
        self.assertIn("none recorded", profile.summary(loaded))

    def test_a_profile_cannot_declare_capabilities(self):
        result = profile.save("42", dict(GOOD, capabilities=["repo.write"]))
        self.assertFalse(result["saved"])
        self.assertIn("profile_authority_key", [problem["code"] for problem in result["problems"]])
        self.assertFalse(profile.load("42")["exists"], "nothing was written")

    def test_a_profile_cannot_store_a_secret(self):
        for key in ("token", "api_key", "secret", "password", "private_key"):
            result = profile.save("42", dict(GOOD, **{key: "value"}))
            self.assertFalse(result["saved"], key)
            self.assertIn("profile_authority_key",
                          [problem["code"] for problem in result["problems"]], key)

    def test_a_nested_secret_is_caught(self):
        result = profile.save("42", dict(GOOD, preferences=dict(secret="x")))
        self.assertFalse(result["saved"])
        self.assertIn("profile_authority_key", [problem["code"] for problem in result["problems"]])

    def test_a_binding_must_use_a_registered_scheme(self):
        result = profile.save("42", dict(GOOD, bindings={"http://evil.example": "x"}))
        self.assertFalse(result["saved"])
        self.assertIn("binding_uri", [problem["code"] for problem in result["problems"]])

    def test_the_answer_view_is_a_narrow_subset(self):
        profile.save("42", dict(GOOD, notes="prefers metric", internal_flag="ignored"))
        view = profile.read_for_answer("42")
        self.assertEqual(sorted(view["shareable"]), ["display_name", "locale", "notes", "preferences"])
        self.assertNotIn("internal_flag", view["shareable"])
        self.assertEqual(view["bindings"], {"srai://user/topic": "dog"})
        self.assertIn("never what it may do", view["note"])

    def test_an_unusable_user_id_is_refused(self):
        for bad in ("../etc", "", "a/b", "x" * 80):
            with self.assertRaises(profile.ProfileError):
                profile.path_for(bad)

    def test_the_path_resolves_at_call_time(self):
        profile.save("42", GOOD)
        self.assertTrue((Path(self.folder.name) / "42.json").is_file())
        other = tempfile.TemporaryDirectory()
        try:
            os.environ["AIML_PROFILES"] = other.name
            self.assertFalse(profile.load("42")["exists"], "the directory is read per call")
        finally:
            other.cleanup()

    def test_a_profile_never_carries_authority_on_disk(self):
        profile.save("42", GOOD)
        written = json.loads((Path(self.folder.name) / "42.json").read_text(encoding="utf-8"))
        self.assertEqual(written["authority"], "declaration_only")
        self.assertNotIn("capabilities", written)


if __name__ == "__main__":
    unittest.main()
