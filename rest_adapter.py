"""`kuhul-rest/v1`: a declarative route manifest, and an adapter that projects permitted data as JSON.

The adapter connects what already exists - HTTP in `micronaut_server`, manifests in `phase_manifest`,
the operator pipeline in `operators` - and adds no engine. A response is a **projection of authorized
data**, never a generated one.

The four guards from the review, each refused with a status and a reason:

    route confinement     method, path, target scheme and the `:param` shape are declared; a path that
                          is not in the manifest is 404, a malformed parameter is 400
    read authorization    the caller must hold the route's capability, and may read only their own
                          resource unless a wider scope is granted; otherwise 403
    projection confinement only the fields the named projection allows are returned; a fact that is not
                          recorded stays missing - nothing is invented
    effect confinement    a GET cannot declare or trigger execution, mutation or persistence; the
                          manifest says so and a guard asserts it

`execution: false` in the manifest means the manifest cannot authorize a model-proposed operation. It
does not stop the trusted HTTP host from performing an explicitly authorized read.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import operators  # noqa: E402
import phase_manifest  # noqa: E402
import user_memory  # noqa: E402

MANIFEST = PACKAGE / "data" / "rest-routes.json"
SCHEMA = "kuhul-rest/v1"
METHODS = ("GET",)
TARGET_SCHEMES = ("gml://", "kuhul://", "aiml://", "srai://")
PARAM_VALUE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
PARAM_TYPES = {"integer": re.compile(r"^\d{1,20}$"), "word": re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"),
               "token": PARAM_VALUE}
# The route names the capability the way the manifest reads; the host grants it under its own name.
CAPABILITY_ALIASES = {"memory.facts.read": "graph.relations.read"}
SUBJECT = "user"


class RouteError(ValueError):
    """A manifest that contradicts the route contract."""


# -- manifest ----------------------------------------------------------------------------------------
def load(path: Path = MANIFEST) -> dict:
    """Parse and validate the route manifest. Declarations that could execute are refused."""
    path = Path(path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, problems=[dict(code="unreadable", detail=str(error))], routes=[],
                    projections={})
    problems: list[dict] = []
    if record.get("schema") != SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {SCHEMA}"))
    if record.get("authority") != "declaration_only":
        problems.append(dict(code="authority", detail="a route manifest is declaration_only"))
    projections = record.get("projections") or {}
    if not isinstance(projections, dict) or not projections:
        problems.append(dict(code="projections", detail="projections must be a non-empty object"))
        projections = {}
    routes = []
    for index, route in enumerate(record.get("routes") or []):
        if not isinstance(route, dict):
            problems.append(dict(code="route_shape", detail=f"#{index}"))
            continue
        where = f"#{index} {route.get('method')} {route.get('path')}"
        method = str(route.get("method") or "").upper()
        if method not in METHODS:
            problems.append(dict(code="method", detail=f"{where}: only {', '.join(METHODS)}"))
        route_path = str(route.get("path") or "")
        if not route_path.startswith("/") or "/:" not in route_path and not re.match(
                r"^/(api|v1)/", route_path):
            problems.append(dict(code="path", detail=f"{where}: path must be /api/... with a :param"))
        target = str(route.get("target") or "")
        if not target.startswith(TARGET_SCHEMES):
            problems.append(dict(code="target", detail=f"{where}: target {target!r}"))
        if not str(route.get("capability") or "").strip():
            problems.append(dict(code="capability", detail=f"{where}: no capability declared"))
        projection = str(route.get("projection") or "")
        if projection not in projections:
            problems.append(dict(code="projection", detail=f"{where}: {projection!r} undeclared"))
        operators_declared = route.get("operators") or []
        unknown = [name for name in operators_declared
                   if name not in ("filter", "map", "fold", "accumulate", "reduce")]
        if unknown:
            problems.append(dict(code="operators", detail=f"{where}: {unknown}"))
        effects = route.get("effects") or {}
        for effect in ("execution", "mutation", "persistence"):
            if effects.get(effect) is not False:
                problems.append(dict(code="effects",
                                     detail=f"{where}: {effect} must be declared false"))
        entry = str(route.get("entry") or "")
        if entry and not entry.startswith("kuhul://phases/"):
            problems.append(dict(code="entry", detail=f"{where}: entry {entry!r}"))
        routes.append(dict(method=method, path=route_path, target=target,
                           capability=str(route["capability"]), projection=projection,
                           operators=list(operators_declared), entry=entry,
                           params=dict(route.get("params") or {}),
                           param=re.search(r":([A-Za-z_][A-Za-z0-9_]*)", route_path).group(1)
                           if re.search(r":([A-Za-z_][A-Za-z0-9_]*)", route_path) else None))
    return dict(ok=not problems, problems=problems, routes=routes, projections=projections,
                authority=record.get("authority"), schema=record.get("schema"))


# -- routing -----------------------------------------------------------------------------------------
def match(manifest: dict, method: str, path: str) -> dict:
    """Route confinement: an unknown method or path is 404, a malformed parameter is 400."""
    method = str(method or "").upper()
    target_path = str(path or "").split("?", 1)[0].rstrip("/") or "/"
    for route in manifest["routes"]:
        pattern = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"(?P<\1>[^/]+)", route["path"])
        found = re.fullmatch(pattern, target_path)
        if found is None:
            continue
        if route["method"] != method:
            return dict(status=404, error="method not allowed for this route", route=route["path"])
        params = found.groupdict()
        declared = route.get("params") or {}
        for name, value in params.items():
            kind = (declared.get(name) or {}).get("type", "token")
            pattern = PARAM_TYPES.get(kind)
            if pattern is None:
                return dict(status=500, error=f"unknown parameter type {kind!r}", route=route["path"])
            if pattern.fullmatch(value or "") is None:
                return dict(status=400, error=f"malformed parameter {name!r} (expected {kind})",
                            route=route["path"])
        return dict(status=200, route=route, params=params)
    return dict(status=404, error="unknown route")


# -- the four guards, then the projection ------------------------------------------------------------
def _facts(user: str) -> list[dict]:
    events = user_memory.events(user)
    latest: dict[tuple[str, str], dict] = {}
    for index, event in enumerate(events):
        payload = event.get("payload") or {}
        if payload.get("type") != "fact_asserted":
            continue
        key = (payload.get("subject") or "", payload.get("predicate") or "")
        latest[key] = dict(subject=key[0], predicate=key[1], value=str(payload.get("value") or ""),
                           event_index=index, event_id=event.get("event_id"))
    return [latest[key] for key in sorted(latest)]


def _resolve_capability(capability: str, granted: set) -> str | None:
    """The manifest's name first, then its declared host alias."""
    if capability in granted:
        return capability
    alias = CAPABILITY_ALIASES.get(capability)
    if alias and alias in granted:
        return alias
    return None


def _authorize(route: dict, params: dict, *, caller: str, granted: set) -> dict:
    if _resolve_capability(route["capability"], granted) is None:
        return dict(ok=False, status=403, reason=f"capability {route['capability']} is not granted")
    identifier = params.get(route["param"] or "")
    if route["target"].startswith("gml://users/") and identifier != caller:
        if "users.read.any" not in granted:
            return dict(ok=False, status=403,
                        reason=f"caller {caller!r} may not read {identifier!r}")
    return dict(ok=True, status=200, identifier=identifier)


def _project_users(identifier: str, projection: list[str]) -> dict:
    """Read the facts, run the operator pipeline, and keep only the permitted fields."""
    facts = _facts(identifier)
    if not facts:
        return dict(body=None, status=404, reason="no records for that resource",
                    allowed=projection, returned=[])
    pipeline = operators.pipeline(
        facts,
        keep=lambda fact: True,
        transform=lambda fact: dict(kind="fact", key=fact["predicate"], value=fact["value"],
                                    ref=f"aiml://memory/{identifier}#{fact['predicate']}"),
        axis="value", mode="max")
    allowed = set(projection)
    body = {fact["predicate"]: fact["value"] for fact in facts if fact["predicate"] in allowed}
    body = dict({"id": identifier} | {key: value for key, value in body.items() if key in allowed})
    withheld = sorted({fact["predicate"] for fact in facts} - allowed)
    return dict(body=body, status=200, allowed=projection, returned=sorted(body),
                withheld=withheld,
                pipeline=[stage["operator"] for stage in pipeline["stages"]])


def _project_phase(name: str, projection: list[str]) -> dict:
    path = PACKAGE / "phases" / "json" / f"{str(name).lower()}.json"
    if not path.is_file():
        return dict(body=None, status=404, reason=f"unknown phase {name!r}")
    loaded = phase_manifest.load(path, root=PACKAGE / "phases" / "json", check_files=False)
    if not loaded["ok"]:
        return dict(body=None, status=400, reason="; ".join(problem["detail"]
                                                           for problem in loaded["problems"]))
    manifest = loaded["manifest"]
    body = {key: manifest[key] for key in projection if key in manifest}
    return dict(body=body, status=200, allowed=projection, returned=sorted(body),
                withheld=sorted(set(manifest) - set(body)))


def handle(method: str, path: str, *, caller: str = "", granted: set | None = None,
           manifest: dict | None = None) -> dict:
    """The whole lifecycle for one request: confine, authorize, project, and never invent."""
    manifest = manifest or load()
    if not manifest["ok"]:
        return dict(status=500, error="route manifest is invalid",
                    problems=manifest["problems"], execution=False)
    granted = set(granted or ())
    routed = match(manifest, method, path)
    if routed["status"] != 200:
        return dict(routed, execution=False, mutation=False, persistence=False,
                    authority="declaration_only")
    route, params = routed["route"], routed["params"]
    authorization = _authorize(route, params, caller=caller or "", granted=granted)
    if not authorization["ok"]:
        return dict(status=authorization["status"], error=authorization["reason"], route=route["path"],
                    execution=False, mutation=False, persistence=False,
                    authority="declaration_only")
    identifier = authorization["identifier"]
    allowed = manifest["projections"][route["projection"]]
    if route["target"].startswith("gml://users/"):
        projected = _project_users(str(identifier), allowed)
    else:
        projected = _project_phase(str(identifier), allowed)
    return dict(status=projected["status"], route=route["path"], method=route["method"],
                projection=route["projection"], allowed=projected.get("allowed", []),
                returned=projected.get("returned", []), withheld=projected.get("withheld", []),
                body=projected.get("body"), error=projected.get("reason"),
                pipeline=projected.get("pipeline"),
                execution=False, mutation=False, persistence=False,
                authority="declaration_only")


def summary(result: dict) -> str:
    line = f"{result.get('method', 'GET')} {result.get('route', '?')} -> {result['status']}"
    detail = []
    if result.get("body") is not None:
        detail.append(f"fields: {', '.join(result.get('returned') or []) or '(none)'}")
    if result.get("withheld"):
        detail.append(f"withheld: {', '.join(result['withheld'])}")
    if result.get("error"):
        detail.append(result["error"])
    if result.get("pipeline"):
        detail.append(f"operators: {' -> '.join(result['pipeline'])}")
    return line + (" · " + " · ".join(detail) if detail else "")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Serve-free check of a kuhul-rest/v1 request.")
    parser.add_argument("path", help="e.g. /api/users/42")
    parser.add_argument("--method", default="GET")
    parser.add_argument("--caller", default="")
    parser.add_argument("--grant", action="append", default=[])
    args = parser.parse_args(argv)
    result = handle(args.method, args.path, caller=args.caller, granted=set(args.grant))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
