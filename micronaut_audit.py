"""Read-only audit of Micronaut declarations, registration claims, and observable routing."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def resolve_ref(ref: str):
    text = str(ref or "")
    if text.startswith(("http://", "https://", "micronaut://", "gml://", "aiml://")):
        return None
    normalized = text.replace("\\", "/")
    if "/" in normalized or normalized.startswith("data/"):
        return ROOT.joinpath(*normalized.split("/"))
    if normalized.endswith(".py"):
        module_parts = normalized[:-3].split(".")
        return ROOT.joinpath(*module_parts).with_suffix(".py")
    parts = normalized.split(".")
    return ROOT.joinpath(*parts[:-1]).with_suffix(".py") if len(parts) > 1 else ROOT / normalized

def report() -> dict:
    semantic = read_json(DATA / "micronauts" / "kuhul-micronaut-registry.json")
    declared = semantic.get("micronauts", {})
    semantic_rows = []
    missing_local_refs = []
    for uri, item in sorted(declared.items()):
        contract = item.get("program_contract", {})
        impl = contract.get("implementation", {})
        caps = item.get("capabilities", {})
        refs = []
        for field in ("program_refs", "grammar_refs", "contract_refs"):
            refs.extend((field, ref) for ref in contract.get(field, []))
        # Check code entry points only when they name a conventional lowercase module path.
        for ref in contract.get("entry_points", []):
            parts = str(ref).split(".")
            if len(parts) >= 3 and all(part and part[0].islower() for part in parts[:-1]):
                refs.append(("entry_point_module", ".".join(parts[:-1]) + ".py"))
        checks = []
        for field, ref in refs:
            candidate = resolve_ref(ref)
            if candidate is None:
                checks.append({"field": field, "ref": ref, "local_check": "not_applicable_uri"})
                continue
            exists = candidate.exists()
            row = {"field": field, "ref": ref, "local_exists": exists}
            if not exists and str(ref).startswith("vendor/key-grammar-kit/"):
                relocated = ROOT.joinpath(*str(ref).replace("\\", "/").removeprefix("vendor/key-grammar-kit/").split("/"))
                if relocated.exists():
                    row["local_exists"] = True
                    row["resolved_path"] = relocated.relative_to(ROOT).as_posix()
                    row["resolution"] = "moved_from_vendor_path"
                    exists = True
            checks.append(row)
            if not exists:
                missing_local_refs.append({"micronaut": uri, "field": field, "ref": ref})
        unresolved_program_refs = [row["ref"] for row in checks
                                   if row.get("field") == "program_refs" and
                                   row.get("local_exists") is False]
        semantic_rows.append({
            "id": uri,
            "source_status": impl.get("source_status", "not_recorded"),
            "runtime_registration": impl.get("runtime_registration", "not_recorded"),
            "validation_status": impl.get("validation_status", "not_recorded"),
            "declared_capabilities": len(caps.get("declared", [])),
            "registered_capabilities": list(caps.get("registered", [])),
            "references": checks,
            "program_reference_status": ("unresolved" if unresolved_program_refs else
                                          "resolved" if contract.get("program_refs") else "not_declared"),
            "unresolved_program_references": unresolved_program_refs,
        })

    engine_dir = ROOT / "kuhul-phase-engine-v0.1.0" / "data"
    engine = read_json(engine_dir / "micronauts.json")
    wiring = read_json(engine_dir / "micronaut-edges.json")
    engine_ids = {entry["uri"] for entry in engine.get("micronauts", [])}
    engine_edges = wiring.get("edges", [])
    endpoint_ok = all(edge.get("from") in engine_ids and edge.get("to") in engine_ids
                      for edge in engine_edges)

    css = read_json(DATA / "manifest" / "css.manifest.json")
    css_bindings = {}
    for key, values in css.items():
        if not key.startswith("micronaut:"):
            continue
        fields = values if isinstance(values, list) else [str(values)]
        css_bindings[key] = {
            "dispatch": next((v.split("=", 1)[1] for v in fields
                               if isinstance(v, str) and v.startswith("dispatch=")), "not_recorded"),
            "implementation_status": next((v.split("=", 1)[1] for v in fields
                                             if isinstance(v, str) and v.startswith("implementation_status=")),
                                            "not_recorded"),
        }

    graph_descriptor = read_json(DATA / "micronauts" / "graph-theory-micronaut.v1.json")
    try:
        import micronaut_host_handlers
        host_handlers = micronaut_host_handlers.bindings()
        graph_handler = micronaut_host_handlers.GRAPH_THEORY_BINDING
    except Exception as error:
        host_handlers = {}
        graph_handler = None
        handler_load_error = f"{type(error).__name__}: {error}"
    else:
        handler_load_error = None
    graph_entry_points = (graph_descriptor.get("program_contract", {}).get("entry_points") or [])
    graph_handler_registered = bool(graph_handler and graph_handler.handler_id in graph_entry_points)
    graph_source = resolve_ref("micronaut/graph_executor.py")
    graph_callable = bool(graph_source and graph_source.is_file() and
                          "def execute_graph_query(" in graph_source.read_text(encoding="utf-8"))
    graph_semantic = next((row for row in semantic_rows if row["id"] == "micronaut:GRAPH-THEORY"), {})
    graph_missing_refs = [row["ref"] for row in graph_semantic.get("references", [])
                          if row.get("local_exists") is False]
    semantic_handler_bindings = {}
    if graph_handler is not None:
        semantic_handler_bindings[graph_handler.uri] = graph_handler
    for row in semantic_rows:
        binding = semantic_handler_bindings.get(row["id"])
        row["host_handler_registered"] = binding is not None
        row["host_handler_id"] = binding.handler_id if binding else None
        row["host_input_schema"] = binding.input_schema if binding else None
        row["host_output_schema"] = binding.output_schema if binding else None
        row["invocation_observed"] = False
    phase_handler_status = []
    for entry in engine.get("micronauts", []):
        uri = entry.get("uri")
        binding = host_handlers.get(uri)
        phase_handler_status.append({
            "uri": uri,
            "declared": True,
            "host_handler_registered": binding is not None,
            "handler_id": binding.handler_id if binding else None,
            "input_contract_matches": bool(binding and binding.input_schema == entry.get("input_schema")),
            "output_contract_matches": bool(binding and binding.output_schema == entry.get("output_schema")),
            "effect": binding.effect if binding else "unbound",
            "invocation_observed": False,
        })
    aiml = (DATA / "alice" / "Bindings.aiml").read_text(encoding="utf-8")
    host_paths = [ROOT / name for name in ("chat_app.py", "aiml_host.py", "daemon.py",
                                           "micronaut_server.py", "micronaut_host_handlers.py")]
    host_text = "\n".join(path.read_text(encoding="utf-8") for path in host_paths if path.exists())
    result = {
        "schema": "kuhul.micronaut-registration-audit/1",
        "scope": str(ROOT),
        "semantic_registry": {
            "document_status": semantic.get("registry_contract", {}).get("document_status"),
            "declared_count": len(semantic_rows),
            "entries": semantic_rows,
            "entries_with_registered_capability_claim": sum(bool(row["registered_capabilities"]) for row in semantic_rows),
            "entries_with_host_handler_binding": sum(row["host_handler_registered"] for row in semantic_rows),
            "entries_with_invocation_observed": 0,
            "entries_with_unresolved_program_references": sum(
                row["program_reference_status"] == "unresolved" for row in semantic_rows),
            "missing_local_references": missing_local_refs,
        },
        "phase_engine_registry": {
            "declared_count": len(engine_ids),
            "edge_count": len(engine_edges),
            "all_edge_endpoints_resolve": endpoint_ok,
            "authority": engine.get("authority"),
            "runtime_handler_invocation": "not_established_by_static_audit",
            "host_handler_bindings": phase_handler_status,
            "handler_load_error": handler_load_error,
            "invocation_evidence": "runtime invocation records are available from Engine.invoke_micronaut; this static audit does not invoke handlers",
        },
        "css_binding_declarations": css_bindings,
        "graph_theory": {
            "descriptor_registration_claim": graph_descriptor.get("registered_status"),
            "descriptor_validation_claim": graph_descriptor.get("program_contract", {}).get("implementation", {}).get("validation_status"),
            "aiml_route_declared": "id=micronaut:GRAPH-THEORY" in aiml,
    "host_calls_graph_theory_entry_point": "graph_executor.execute_graph_query(" in host_text,
            "generic_phase_catalog_uses_declared_route_function":
                "micronaut_registry.route(" in host_text,
            "live_dispatch": "not_verified_by_static_audit",
            "host_handler_registered": graph_handler_registered,
            "host_handler_contract_matches_entry_point": graph_handler_registered,
            "entry_point_callable_present": graph_callable,
            "invocation_observed": False,
            "unresolved_program_refs": graph_missing_refs,
        },
        "notes": [
            "Catalog entries and GML/AIML routes are declarations, not executable handler registration.",
            "The phase-engine registry selects declared edges; it does not invoke handlers or grant XCFE admission.",
            "Static source inspection cannot prove whether an external process or service handles a declared route."
        ]
    }
    return result


def main() -> int:
    print(json.dumps(report(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
