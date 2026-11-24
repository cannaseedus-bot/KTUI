"""A local user profile: configuration a bot may read, and never an authority it could use.

The design the review implied - no OAuth, no login, a profile file per local user - is the right shape for a bot
that runs on one machine. What it must not become is a second place where permissions live. So:

    profile.json    name, locale, preferences, and AIML/SRAI bindings      data a bot may read
    capabilities    refused at load                                       the engine's grants are the only grants
    secrets         refused at load                                       a token in a profile is a token in a prompt
    read_for_answer the narrow, shareable subset a turn may mention       never the whole file

A profile may tell the bot to use `srai://user/preferred_topic`; it may never tell the bot it holds `repo.write`.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
SCHEMA = "kuhul://profile/v1"
# Keys that would turn a profile into an authority grant or a secret store. Refused, not ignored.
FORBIDDEN_KEYS = ("capabilities", "grants", "permissions", "role_authority", "token", "tokens",
                  "api_key", "apikey", "secret", "secrets", "password", "passphrase",
                  "private_key", "authorization")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class ProfileError(ValueError):
    """A profile that tries to be more than configuration."""


def profiles_dir() -> Path:
    """Resolved at call time: tests and other hosts point this somewhere else."""
    return Path(os.environ.get("AIML_PROFILES") or (HOST_ROOT / "profiles"))


def path_for(user: str) -> Path:
    identifier = str(user or "").strip()
    if not IDENTIFIER.fullmatch(identifier):
        raise ProfileError(f"{user!r} is not a usable user id")
    return profiles_dir() / f"{identifier}.json"


def _scan(value, where: str = "") -> list[dict]:
    problems: list[dict] = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key).lower()
            if name in FORBIDDEN_KEYS:
                problems.append(dict(code="profile_authority_key",
                                     detail=f"{where}{key}: a profile may not declare {key}"))
            problems.extend(_scan(item, f"{where}{key}."))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            problems.extend(_scan(item, f"{where}{index}."))
    return problems


def validate(record: dict) -> dict:
    """Shape and vocabulary. A profile is data; anything that looks like authority is a refusal."""
    problems: list[dict] = []
    if not isinstance(record, dict):
        return dict(ok=False, problems=[dict(code="shape", detail="a profile must be an object")])
    if record.get("schema") not in (None, SCHEMA):
        problems.append(dict(code="schema", detail=f"expected {SCHEMA}"))
    if record.get("authority") not in (None, "declaration_only"):
        problems.append(dict(code="authority", detail="a profile is declaration_only"))
    problems.extend(_scan(record))
    bindings = record.get("bindings") or {}
    if not isinstance(bindings, dict):
        problems.append(dict(code="bindings", detail="bindings must be an object"))
    else:
        for key, value in bindings.items():
            if not str(key).startswith(("aiml://", "srai://", "gml://", "kuhul://")):
                problems.append(dict(code="binding_uri", detail=f"{key!r} is not a registered scheme"))
            if not isinstance(value, (str, int, float, bool)):
                problems.append(dict(code="binding_value", detail=f"{key} must be a scalar"))
    return dict(ok=not problems, problems=problems, record=record)


def load(user: str, *, path: Path | None = None) -> dict:
    """Read a profile. A missing file is an empty profile, not an error."""
    path = Path(path) if path else path_for(user)
    if not path.is_file():
        return dict(schema=SCHEMA, user=str(user), profile={}, exists=False,
                    ok=True, problems=[], authority="declaration_only")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(schema=SCHEMA, user=str(user), profile={}, exists=True, ok=False,
                    problems=[dict(code="unreadable", detail=str(error))],
                    authority="declaration_only")
    checked = validate(record)
    return dict(schema=SCHEMA, user=str(user), profile=record, exists=True,
                ok=checked["ok"], problems=checked["problems"], path=str(path),
                authority="declaration_only")


def save(user: str, profile: dict, *, path: Path | None = None) -> dict:
    """Write a profile after validating it. Secrets and capability claims never reach the disk."""
    checked = validate(profile)
    if not checked["ok"]:
        return dict(schema=SCHEMA, user=str(user), saved=False, problems=checked["problems"],
                    authority="declaration_only")
    path = Path(path) if path else path_for(user)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(checked["record"], schema=SCHEMA, user=str(user), authority="declaration_only")
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dict(schema=SCHEMA, user=str(user), saved=True, path=str(path), problems=[],
                authority="declaration_only")


def read_for_answer(user: str, *, path: Path | None = None) -> dict:
    """The shareable subset: display name, locale, preferences and nothing that could look like a grant."""
    loaded = load(user, path=path)
    if not loaded["ok"]:
        return dict(shareable={}, refused="profile_invalid", problems=loaded["problems"],
                    authority="declaration_only")
    profile = loaded["profile"] or {}
    shareable = {}
    for key in ("display_name", "locale", "timezone", "preferences", "notes"):
        if key in profile:
            shareable[key] = profile[key]
    return dict(shareable=shareable, refused=None, exists=loaded["exists"],
                bindings=dict((profile.get("bindings") or {})),
                authority="declaration_only",
                note=("configuration only: a profile can steer what the bot says, never what it may do"))


def summary(loaded: dict) -> str:
    if not loaded.get("ok"):
        return f"profile {loaded.get('user')} · INVALID · " + "; ".join(
            problem["code"] for problem in loaded["problems"])
    if not loaded.get("exists"):
        return f"profile {loaded.get('user')!r} · none recorded"
    profile = loaded["profile"] or {}
    fields = ", ".join(sorted(key for key in profile
                              if key not in ("schema", "user", "authority"))) or "(empty)"
    return f"profile {loaded['user']!r} · {fields} · declaration_only"
