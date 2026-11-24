"""`runtime://green-screen/v1`: one read-only projection of the running system, for reasoning and display.

The registries already exist - phase manifests, micronauts, model router and lifecycle, corpus, evidence
records - and this module joins them into a single typed tree that both the phase hive and the Textual UI
can read. It adds no authority: every node carries `authority: "declaration_only"`, and nothing here can
change a binding, start a model or admit a proposal.

Two things it makes answerable from real data rather than from memory:

    which micronauts do not use the advisor                walk micronaut -> model edges
    why did the router choose one model over another       `explain_selection`, from routing + health +
                                                           features + the rejected alternatives

Textual is the renderer; this is the semantic field it draws. The GML/registry/phase contracts stay
authoritative, and the screen only ever shows their verified state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import corpus  # noqa: E402
import evidence_record  # noqa: E402
import micronaut_registry  # noqa: E402
import model_lifecycle  # noqa: E402
import model_router  # noqa: E402
import phase_manifest  # noqa: E402

SCHEMA = "runtime://green-screen/v1"
PHASE_DIR = PACKAGE / "phases" / "json"


def _node(identifier: str, kind: str, label: str, **fields) -> dict:
    return dict(id=identifier, kind=kind, label=label, authority="declaration_only",
                fields={key: value for key, value in fields.items() if value is not None})


def projection(*, host: dict | None = None, lifecycle_view: dict | None = None) -> dict:
    """Build the tree from the live registries. Missing or broken inputs degrade to a node, never a crash."""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add(node: dict) -> dict:
        nodes[node["id"]] = node
        return node

    def link(source: str, relation: str, target: str) -> None:
        if source in nodes and target in nodes:
            edges.append(dict(source=source, relation=relation, target=target))

    add(_node("runtime://daemon-bot", "runtime", "Daemon Bot",
              schema=SCHEMA, note="read-only projection; the registries are authoritative"))

    # -- phases -------------------------------------------------------------------------------------
    # `discover` reports phase names and their manifest paths; each manifest is loaded for its fields.
    discovered = phase_manifest.discover(PHASE_DIR) if PHASE_DIR.is_dir() else dict(manifests={})
    for name, paths in (discovered.get("manifests") or {}).items():
        identifier = f"phase://{str(name).lower().replace(chr(39), '')}"
        manifest = {}
        for candidate in paths or []:
            loaded = phase_manifest.load(Path(candidate), root=PHASE_DIR, check_files=False)
            if loaded.get("ok"):
                manifest = loaded["manifest"]
                break
        add(_node(identifier, "phase", str(name), uri=manifest.get("uri"),
                  phase_next=manifest.get("next"), bindings=len(manifest.get("bindings") or []),
                  authority=manifest.get("authority")))
        link("runtime://daemon-bot", "has_phase", identifier)
        following = str(manifest.get("next") or "")
        if following:
            link(identifier, "precedes",
                 f"phase://{following.rstrip('/').split('/')[-1].lower().replace(chr(39), '')}")

    # -- micronauts and their schemas ---------------------------------------------------------------
    registry = micronaut_registry.load()
    for entry in registry.get("list") or []:
        identifier = entry["uri"]
        add(_node(identifier, "micronaut", entry["uri"].split("/")[-1],
                  role=entry["role"], entry_phase=entry["entry"],
                  input_schema=entry["input_schema"], output_schema=entry["output_schema"],
                  operators=entry["operators"], capabilities=entry["capabilities"]))
        link("runtime://daemon-bot", "has_micronaut", identifier)
        if entry["input_schema"]:
            schema_id = f"schema://{entry['input_schema'].split('/')[-2] if '/' in entry['input_schema'] else entry['input_schema']}"
            add(_node(schema_id, "schema", entry["input_schema"]))
            link(identifier, "accepts", schema_id)
    for edge in registry.get("edges") or []:
        link(edge["source"], "hands_off_to", edge["target"])

    # -- models, their state, and the bindings ------------------------------------------------------
    declaration = model_lifecycle.load()
    for name, entry in (declaration.get("by_name") or {}).items():
        identifier = f"model://{name}"
        current = "unknown"
        try:
            current = model_lifecycle.state(declaration, name, host=host)["state"]
        except Exception:
            current = "unknown"
        # Observed, never initiated: a screen that refreshes must not wake or stop anything.
        observed = lifecycle_view.get(name, {}) if lifecycle_view else {}
        add(_node(identifier, "model", name, role=entry["role"], port=entry["launch"]["port"],
                  state=current, features=entry["features"],
                  idle_timeout_seconds=entry["idle_timeout_seconds"],
                  declared_state=entry["state"],
                  leases=observed.get("leases"),
                  owned=observed.get("owned"),
                  idle_remaining=observed.get("idle_remaining")))
        link("runtime://daemon-bot", "has_model", identifier)
    for micronaut, model in (declaration.get("router", {}).get("routing") or {}).items():
        link(micronaut, "binds_to", f"model://{model}")
    for rank_name, order in (declaration.get("router", {}).get("preferences") or {}).items():
        identifier = f"preference://{rank_name}"
        add(_node(identifier, "preference", rank_name, order=list(order)))
        link("runtime://daemon-bot", "has_preference", identifier)
        for model in order:
            link(identifier, "prefers", f"model://{model}")

    # -- corpus --------------------------------------------------------------------------------------
    corpus_declaration = corpus.load()
    for uri, source in (corpus_declaration.get("sources") or {}).items():
        identifier = f"corpus://{uri.split('://')[-1].replace('/', '.')}"
        add(_node(identifier, "corpus", uri, source_kind=source["kind"],
                  scope=source["scope"], available=source["available"],
                  capability=source["capability"]))
        link("runtime://daemon-bot", "has_corpus", identifier)

    # -- evidence ------------------------------------------------------------------------------------
    records = evidence_record.load()
    chain = evidence_record.verify()
    add(_node("evidence://ledger", "evidence", "inference records",
              records=len(records), chain_ok=bool(chain.get("ok")),
              last_request_id=(records[-1].get("request_id") if records else None)))
    link("runtime://daemon-bot", "has_evidence", "evidence://ledger")
    if records:
        last = records[-1]
        if last.get("binding"):
            link("evidence://ledger", "records_binding", f"model://{last['binding']}")

    return dict(schema=SCHEMA, nodes=sorted(nodes.values(), key=lambda item: item["id"]),
                edges=sorted(edges, key=lambda item: (item["source"], item["relation"], item["target"])),
                by_id=nodes, authority="declaration_only", execution=False, mutation=False)


def query(tree: dict, identifier: str) -> dict | None:
    return (tree.get("by_id") or {}).get(str(identifier))


def neighbours(tree: dict, identifier: str, relation: str | None = None) -> dict:
    """Outgoing and incoming edges, optionally filtered by relation - the traversal the phases need."""
    outgoing = [edge for edge in tree["edges"]
                if edge["source"] == identifier and (relation is None or edge["relation"] == relation)]
    incoming = [edge for edge in tree["edges"]
                if edge["target"] == identifier and (relation is None or edge["relation"] == relation)]
    return dict(id=identifier, outgoing=outgoing, incoming=incoming)


def explain_selection(tree: dict, micronaut: str) -> dict:
    """Why the router would choose one model - from routing, health, features and rejected alternatives."""
    router = model_router.load()
    probes = model_router.healthy(router)
    binding = model_router.select(router, micronaut, probes=probes)
    return dict(schema="runtime://selection/1", micronaut=str(micronaut),
                declared=(router.get("routing") or {}).get(str(micronaut)),
                selected=binding.get("selected"), ok=bool(binding.get("ok")),
                refused=binding.get("refused"), order=binding.get("order"),
                rejected=binding.get("rejected"),
                health={name: bool(probe.get("ok")) for name, probe in probes.items()},
                authority="declaration_only", admitted=False, execution=False,
                note="a binding names a backend; admitting or invoking it is a separate decision")


def users_of(tree: dict, model: str) -> list[dict]:
    """Which micronauts bind to one model - the review's 'who uses the advisor' question."""
    name = model.split("/")[-1]
    return neighbours(tree, f"model://{name}", "binds_to")["incoming"]


def render(tree: dict, *, limit: int = 40) -> str:
    """A compact text view for the TUI. Pure projection: no colour, no invention."""
    counts: dict[str, int] = {}
    for node in tree["nodes"]:
        counts[node["kind"]] = counts.get(node["kind"], 0) + 1
    lines = [f"{tree['schema']} · {len(tree['nodes'])} node(s) · {len(tree['edges'])} edge(s)"]
    lines.append("  " + " · ".join(f"{kind} {count}" for kind, count in sorted(counts.items())))
    for node in tree["nodes"]:
        if node["kind"] == "model":
            lines.append(f"  {node['id']:22} {node['fields'].get('state', '?'):5} "
                         f"port {node['fields'].get('port')}")
    for node in tree["nodes"]:
        if node["kind"] == "evidence":
            lines.append(f"  {node['id']:22} records {node['fields'].get('records')} · "
                         f"chain {'ok' if node['fields'].get('chain_ok') else 'BROKEN'}")
    for node in tree["nodes"][:limit]:
        if node["kind"] in ("phase", "micronaut"):
            lines.append(f"  {node['id']:28} {node['fields'].get('role') or node['fields'].get('uri') or ''}")
    lines.append("  (read-only projection · the registries and XCFE are authoritative)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Read-only runtime projection.")
    parser.add_argument("--explain", help="explain the model selection for a micronaut uri")
    parser.add_argument("--json", action="store_true", help="print the tree as json")
    args = parser.parse_args(argv)
    tree = projection()
    if args.explain:
        print(json.dumps(explain_selection(tree, args.explain), indent=2))
        return 0
    if args.json:
        print(json.dumps({key: tree[key] for key in ("schema", "nodes", "edges")}, indent=2))
        return 0
    print(render(tree))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

# -- reactive projection: a digest that changes only when the semantics change -------------------------
# Volatile fields would make the screen refresh on every turn (a record count, a timestamp, a latency).
# The digest covers what the green screen actually claims: structure and declared state.
VOLATILE_FIELDS = ("records", "last_request_id", "chain_ok", "latency_ms", "recorded_at",
                   "observed_execution", "tokens", "idle_remaining")


def _semantic(node: dict) -> dict:
    fields = {key: value for key, value in (node.get("fields") or {}).items()
              if key not in VOLATILE_FIELDS}
    return dict(id=node["id"], kind=node["kind"], label=node["label"],
                authority=node.get("authority"), fields=fields)


def semantic_digest(tree: dict) -> str:
    """A stable digest of the projection's meaning: same state, same digest."""
    import hashlib

    payload = dict(nodes=[_semantic(node) for node in tree.get("nodes") or []],
                   edges=sorted((edge["source"], edge["relation"], edge["target"])
                                for edge in tree.get("edges") or []))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def watch(*, host: dict | None = None, lifecycle_view: dict | None = None) -> dict:
    """Build a projection and its digest. Pure: it reads the registries and starts nothing."""
    tree = projection(host=host, lifecycle_view=lifecycle_view)
    return dict(tree=tree, digest=semantic_digest(tree),
                counts={kind: sum(1 for node in tree["nodes"] if node["kind"] == kind)
                        for kind in sorted({node["kind"] for node in tree["nodes"]})})

