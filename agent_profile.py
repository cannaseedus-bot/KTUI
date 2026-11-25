"""The first AGENT.md consumer: identity and route preferences, and never a grant.

The file declares who the Micro Agent is and which **declared route** it prefers for a kind of work. Two rules keep it
harmless, and both are enforced here rather than described:

    a preference names a route, never a target   "reasoning_route: ASK_PLANNER", not "model://planner"
    a persona never grants                        authority keys are refused at load

Identity is checked against what exists: the parent Micronaut must be a registered handler, and every preferred route
must resolve through the host's declared table. A file that fails either check is reported, not silently tolerated.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import micro_agent_bridge  # noqa: E402
import micronaut_host_handlers  # noqa: E402

SCHEMA = "kuhul://agent/profile/v1"
DEFAULT_PATH = HOST_ROOT / "AGENT.md"
# A persona that tries to become an authority source is refused, exactly like a profile that does.
FORBIDDEN_KEYS = ("capabilities", "grants", "permissions", "scopes", "token", "tokens", "api_key",
                  "secret", "password", "role_authority", "execution", "mutation")
PREFERENCE_SUFFIX = "_route"


class AgentError(ValueError):
    """An agent declaration the host will not accept."""


def parse(text: str) -> dict:
    """`key: value` lines plus `## Sections`. Small on purpose: this is a declaration, not a document format."""
    fields: dict[str, str] = {}
    sections: dict[str, str] = {}
    current = None
    buffer: list[str] = []
    # A field is `name: value` with a bare lower-case name, whether it sits above a heading or inside one, so
    # `## Preferred routes` can hold preferences without turning them into prose.
    field_line = re.compile(r"^([a-z][a-z0-9_]*):\s*(\S.*)$")
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            if current:
                sections[current] = "\n".join(buffer).strip()
            current = line[3:].strip().lower()
            buffer = []
            continue
        match = field_line.match(line.strip())
        if match:
            fields[match.group(1)] = match.group(2).strip()
            continue
        if current is not None:
            buffer.append(line)
    if current:
        sections[current] = "\n".join(buffer).strip()
    return dict(fields=fields, sections=sections)


def registered_handlers() -> set[str]:
    host = micronaut_host_handlers.HandlerHost(
        identity="agent-profile-check", granted=set(),
        policy=lambda binding, payload: getattr(binding, "effect", None) == "read_only")
    return set(getattr(host, "bindings", {}) or {})


def load(path: Path | None = None, *, declaration: dict | None = None) -> dict:
    """Read and validate AGENT.md. Returns the preferences it may act on, or a named refusal."""
    path = Path(path or DEFAULT_PATH)
    routes = declaration if declaration is not None else micro_agent_bridge.DECLARED_ROUTES
    if not path.is_file():
        return dict(schema=SCHEMA, ok=False, refused="agent_missing", detail=f"{path} does not exist",
                    agent=None, preferences={}, persona=None, authority="declaration_only")
    parsed = parse(path.read_text(encoding="utf-8"))
    fields, sections = parsed["fields"], parsed["sections"]
    problems: list[dict] = []

    agent_id = fields.get("agent_id", "").strip()
    if not agent_id:
        problems.append(dict(code="agent_id_missing", detail="a Micro Agent needs an identity"))

    parent = fields.get("parent_micronaut", "").strip()
    if not parent:
        problems.append(dict(code="parent_missing", detail="a Micro Agent needs a parent Micronaut"))
    elif not parent.startswith("micronaut://"):
        problems.append(dict(code="parent_scheme", detail=f"{parent!r} is not a micronaut URI"))
    elif parent not in registered_handlers():
        problems.append(dict(code="parent_not_registered",
                             detail=f"{parent!r} is not a registered handler"))

    preferences: dict[str, str] = {}
    for key, value in fields.items():
        if not key.endswith(PREFERENCE_SUFFIX):
            continue
        kind = key[: -len(PREFERENCE_SUFFIX)]
        if value.startswith(("model://", "micronaut://")):
            problems.append(dict(code="preference_is_target",
                                 detail=(f"{key} names a target ({value}); a preference names a declared route")))
            continue
        if value not in routes:
            problems.append(dict(code="route_not_declared",
                                 detail=f"{key}: {value!r} is not a declared route"))
            continue
        preferences[kind] = value

    for key in fields:
        if key in FORBIDDEN_KEYS:
            problems.append(dict(code="agent_authority_key",
                                 detail=f"{key}: an agent may not declare authority"))
    for name in sections:
        if name in FORBIDDEN_KEYS:
            problems.append(dict(code="agent_authority_section",
                                 detail=f"section {name!r} may not declare authority"))

    return dict(schema=SCHEMA, ok=not problems, refused=None if not problems else problems[0]["code"],
                agent=dict(agent_id=agent_id, parent_micronaut=parent),
                persona=(sections.get("persona") or "").strip() or None,
                preferences=preferences, problems=problems,
                authority="declaration_only", grants=[],
                note=("identity and route preferences only: this file cannot grant a capability or authorize "
                      "execution"))


def route_for(kind: str, *, profile: dict | None = None) -> str | None:
    """The declared route this agent prefers for a kind of work, if the declaration is valid."""
    loaded = profile if profile is not None else load()
    if not loaded.get("ok"):
        return None
    return (loaded.get("preferences") or {}).get(str(kind or "").strip().lower())


def summary(loaded: dict) -> str:
    if not loaded.get("ok"):
        return f"agent · NOT AVAILABLE · {loaded.get('refused')} · {loaded.get('detail') or ''}".strip()
    agent = loaded.get("agent") or {}
    preferences = ", ".join(f"{kind}={route}" for kind, route in sorted(loaded["preferences"].items())) or "(none)"
    return (f"agent · {agent.get('agent_id')} · parent {agent.get('parent_micronaut')} · "
            f"routes {preferences} · personality only, no grants")
