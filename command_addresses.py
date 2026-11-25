"""Declaration-only command-address grammar shared by AIML, Micronauts, and model proposals.

Resolving a command string produces a typed candidate.  It never invokes a tool, runs a verb,
selects a model, persists a delta, or grants execution authority.
"""
from __future__ import annotations

from urllib.parse import urlsplit

import gml_columns


SCHEMA = "kuhul://command-address/1"
FAMILIES = {
    "srai": dict(responsibility="redirect", result="resolved_intent"),
    "delta": dict(responsibility="learning_or_graph_proposal", result="typed_delta_proposal"),
    "tool": dict(responsibility="registered_tool_request", result="tool_result"),
    "verb": dict(responsibility="graph_operator_selection", result="typed_computation_result"),
    "micronaut": dict(responsibility="registered_micronaut_capability", result="typed_handler_result"),
    "model": dict(responsibility="registered_model_selection", result="candidate_text"),
}


class CommandAddressError(ValueError):
    pass


def _generic(family: str, uri: str, parsed) -> dict:
    if not parsed.netloc:
        raise CommandAddressError(f"{family} command requires a target namespace: {uri!r}")
    spec = FAMILIES[family]
    return dict(schema=SCHEMA, uri=uri, family=family, target=parsed.netloc + parsed.path,
                responsibility=spec["responsibility"], result=spec["result"],
                route_declared=False, command_candidate=True, authority="declaration_only",
                admitted=False, execution=False, mutation=False, persistence=False,
                note="accepted as a command candidate; the host must resolve a registered route")


def resolve(uri: str, *, catalog: dict | None = None) -> dict:
    """Parse one command URI and resolve only declarations that already exist."""
    text = str(uri or "").strip()
    parsed = urlsplit(text)
    if parsed.scheme not in FAMILIES or parsed.query or parsed.fragment:
        raise CommandAddressError(f"unregistered command family or malformed URI: {uri!r}")
    family = parsed.scheme
    if family == "verb":
        if parsed.netloc != "graph":
            raise CommandAddressError(f"verb target must use graph namespace: {uri!r}")
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) == 1:
            canonical = f"{gml_columns.ROOT_URI}/operators/{parts[0]}"
        elif len(parts) == 3 and parts[1] == "columns":
            canonical = f"{gml_columns.ROOT_URI}/operators/{parts[0]}/columns/{parts[2]}"
        else:
            raise CommandAddressError(f"invalid graph verb address: {uri!r}")
        target = gml_columns.resolve_address(canonical, catalog=catalog)
        return dict(schema=SCHEMA, uri=text, family=family, target=target,
                    responsibility=FAMILIES[family]["responsibility"],
                    result=FAMILIES[family]["result"], route_declared=True,
                    command_candidate=True, authority="declaration_only", admitted=False,
                    execution=False, mutation=False, persistence=False,
                    note="operator declaration resolved; typed edge binding and host admission remain required")
    if family == "micronaut":
        target = gml_columns.resolve_address(text, catalog=catalog) \
            if text.startswith("micronaut://gml/") else None
        return dict(schema=SCHEMA, uri=text, family=family, target=target,
                    responsibility=FAMILIES[family]["responsibility"],
                    result=FAMILIES[family]["result"], route_declared=target is not None,
                    command_candidate=True, authority="declaration_only", admitted=False,
                    execution=False, mutation=False, persistence=False,
                    note="Micronaut address is a candidate; host admission is still required")
    return _generic(family, text, parsed)


def validate_candidate(candidate: dict) -> dict:
    """Keep command candidates separate from authorized operations."""
    if not isinstance(candidate, dict) or candidate.get("schema") != SCHEMA:
        return dict(ok=False, refused="schema_mismatch", admitted=False, execution=False)
    if candidate.get("command_candidate") is not True:
        return dict(ok=False, refused="not_a_command_candidate", admitted=False, execution=False)
    return dict(ok=True, uri=candidate.get("uri"), family=candidate.get("family"),
                route_declared=bool(candidate.get("route_declared")), admitted=False,
                execution=False, mutation=False, persistence=False,
                authority="declaration_only")
