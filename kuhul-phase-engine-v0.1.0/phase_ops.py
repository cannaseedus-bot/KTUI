"""Declared phase operations, classified: registered, requires-grant, proposal-only or unbound.

The six phase banks declare 58 operations in their headers (112 categories in total). This module asks
the only question that matters for integration: **for each declared operation, what actually exists?**

    registered      a host capability exists and is importable (named, and verified callable)
    requires_grant  the host has only a gated path (`/allow`, `/allow git`, XCFE); a matched pattern
                    never reaches it by itself
    proposal_only   the host can only propose it (a plan, a candidate, a declaration)
    unbound         declared, and nothing implements it yet

The classification is a declared table, not a guess: an operation that is missing from the table cannot
silently become "registered", and `registered` entries are checked by importing the capability.

**A declaration is not permission.** `sek.aiml` declares `execute_tool_chain` and `dispatch_call`;
`xul.aiml` declares `gramWrite`, `persist_state` and `compare_and_commit`. Matching one of their
patterns grants nothing - those operations are `requires_grant`, and the report says so in a list a
reviewer can check without reading six files.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# The audit names host capabilities, so the host and the package's core must be importable from here.
for _candidate in (str(ROOT.parent), str(ROOT / "core"), str(ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)
PHASES_DIR = ROOT / "phases"
BANKS = ("pop", "wo", "yax", "sek", "chen", "xul")
STATUSES = ("registered", "requires_grant", "proposal_only", "unbound")
STOP = re.compile(r"^(Channels:|terminal:|Hylomorphism|FS\d|Only authorized|-->)")
OPS = re.compile(r"Ops:\s*(.*?)(?=\n\s*(?:Channels:|terminal:|Hylomorphism|FS\d|Only authorized|-->))",
                 re.S)

# The table. A capability is `module.function` for `registered`; a reason for everything else.
BINDINGS: dict[str, tuple[str, str]] = {
    # Pop - activation and matching
    "gramRead": ("unbound", "reading the grammar is done by the host loader, not an operation"),
    "manifest_lookup": ("registered", "phase_manifest.load"),
    "lexical_activate_candidates": ("registered", "aiml_graph.match"),
    "find_best_pattern_match": ("registered", "aiml_graph.match"),
    "sense_inventory_lookup": ("unbound", "no sense inventory exists"),
    "candidate_sense_bind": ("unbound", "no sense inventory exists"),
    "embedgemma_prompt_vectorize": ("unbound", "no EmbeddingGemma2 encoder in this repository"),
    "key_lane_bind": ("registered", "phase_resolve.eliza_fields"),
    "mx2lm_ngram_lane_bind": ("registered", "phase_resolve.eliza_fields"),
    "micronaut_context_fanout": ("proposal_only", "phase_resolve lists candidate intents"),
    "mathml_query_detect": ("unbound", "no MathML reader"),
    "xcfe_condition_check": ("registered", "aiml_host.states"),
    "srai_intent_detect": ("registered", "srai_resolver.is_redirect"),
    # Wo - binding and guards
    "state_and_constraints": ("registered", "phase_resolve.eliza_fields"),
    "unfold_linguistic_resolution": ("proposal_only", "phase_resolve proposes the fields"),
    "decompose_task": ("registered", "greetings.routes"),
    "plan_task": ("registered", "planner.resolve"),
    "xcfe_auth_check": ("registered", "aiml_host.states"),
    "srai_recursion_guard_init": ("registered", "srai_resolver.resolve"),
    # Yax - traversal and projection
    "admit_neighborhood": ("unbound", "no neighborhood admitter; the projection has no traversal"),
    "compose": ("registered", "compose.paragraph"),
    "aggregate": ("registered", "compose.compose"),
    "resolve_eliza_field_candidates": ("registered", "phase_resolve.eliza_fields"),
    "graph_bfs": ("unbound", "user_memory.graph builds the projection; no BFS over it"),
    "srai_program_project": ("registered", "aiml_graph.answer"),
    "pi_triangle_route": ("proposal_only", "the vector triangle ranks; routing is the host's"),
    # Sek - construction and proposals
    "compute_over_admitted_structure": ("registered", "compose.retrieve"),
    "resolve_xaiml_candidate": ("registered", "aiml_graph.match"),
    "select_eliza_field_candidate": ("registered", "phase_resolve.eliza_fields"),
    "execute_tool_chain": ("requires_grant", "tool execution needs the host's /allow and admission"),
    "srai_xcfe_propose": ("proposal_only", "srai_resolver resolves; admission is XCFE's"),
    "dispatch_call": ("requires_grant", "dispatching a call is execution, not a proposal"),
    "build_ngrams": ("unbound", "no n-gram builder"),
    "emit_fold_delta_proposal": ("proposal_only", "phase_resolve proposes the fold plan"),
    "map_paragraph_claim": ("registered", "compose.compose"),
    "fold_paragraph_accumulator": ("registered", "compose.compose"),
    "map_cfpc_question_candidate": ("proposal_only", "phase_resolve lists candidates"),
    "filter_cfpc_question_candidates": ("registered", "compose.retrieve"),
    "rank_cfpc_question_candidates": ("registered", "compose.retrieve"),
    "fold_cfpc_question_set": ("proposal_only", "the fold is proposed, not applied"),
    # Ch'en - verification
    "assert_and_verify_candidate": ("registered", "aiml_host.validate"),
    "verify_eliza_candidate_provenance": ("registered", "compose.verify"),
    "verify_srai_recursion_limits": ("registered", "srai_resolver.resolve"),
    "verify_semantic_invariance": ("registered", "aiml_host.states"),
    "verify_relation_invariance": ("registered", "aiml_host.states"),
    "verify_syntax_constraints": ("registered", "aiml_host.validate"),
    "verify_delegation": ("registered", "phase_resolve.resolve_aiml"),
    "verify_ngram_confidence": ("unbound", "no n-gram confidence exists"),
    "classify_resolution": ("registered", "phase_resolve._xul"),
    "store_rejected_candidate_evidence": ("registered", "ledger_plugin.append"),
    # Xul - closure, all gated
    "compare_and_commit": ("requires_grant", "committing is a write; XCFE authorizes it"),
    "gramWrite": ("requires_grant", "writing the gram needs a host grant"),
    "record_phase_evidence": ("registered", "ledger_plugin.append"),
    "emit_answer": ("proposal_only", "the host renders the answer; a phase cannot emit by matching"),
    "persist_state": ("requires_grant", "persistence is gated by XCFE"),
    "fold_reasoning_result": ("registered", "compose.compose"),
    "update_authorized_metric_parameters": ("requires_grant", "metric writes are authorized changes"),
    "invalidate_dependent_projections": ("requires_grant", "invalidating projections is a write"),
}



# Operations whose name means "change something". They may be classified `requires_grant` or
# `proposal_only`; a `registered` status for any of them is a defect, not a convenience.
GATED_NAMES = ("execute_tool_chain", "dispatch_call", "compare_and_commit", "gramWrite",
               "persist_state", "update_authorized_metric_parameters",
               "invalidate_dependent_projections")


def violations(table: dict | None = None) -> list[dict]:
    """Any gated operation that claims to be registered - the rule this table must never break."""
    table = BINDINGS if table is None else table
    return [dict(code="gated_but_registered", detail=name)
            for name in GATED_NAMES if table.get(name, ("", ""))[0] == "registered"]


def header(path: Path) -> dict:
    """The phase header: phase, order, theta, verb, declared ops, channels, terminal."""
    text = Path(path).read_text(encoding="utf-8")
    # The Ops block is unique per file, but it is not always before the first category: xul.aiml opens
    # with a proposal category. Search the document rather than a prefix of it.
    head = text
    found = OPS.search(head)
    ops = []
    if found:
        ops = [item.strip() for item in re.split(r",|\n", found.group(1))
               if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item.strip())]

    def field(name, pattern, cast=str):
        match = re.search(pattern, head, re.M)
        return cast(match.group(1).strip()) if match else None

    return dict(bank=Path(path).stem,
                phase=field("phase", r"^\s*Phase:\s*([A-Za-z']+)"),
                order=field("order", r"phase_order:\s*(\d+)", int),
                theta=field("theta", r"theta:\s*(\d+)", int),
                verb=field("verb", r"default_verb:\s*(@[a-z_]+)"),
                terminal=field("terminal", r"terminal:\s*(true|false)") == "true",
                categories=text.count("<category>"),
                ops=ops)


def inventory(folder: Path = PHASES_DIR) -> dict:
    """All six banks: headers, categories and the declared operation list."""
    banks = [header(Path(folder) / f"{name}.aiml") for name in BANKS]
    ops = [op for bank in banks for op in bank["ops"]]
    return dict(banks=banks, ops=ops, total_ops=len(ops), unique_ops=len(set(ops)),
                categories=sum(bank["categories"] for bank in banks),
                phases=[bank["phase"] for bank in banks])


def _callable(path: str):
    module_name, _, attribute = path.partition(".")
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
    target = getattr(module, attribute, None)
    return target if callable(target) else None


def classify(folder: Path = PHASES_DIR, *, verify: bool = True) -> dict:
    """Attach a status to every declared operation, and verify the registered ones exist."""
    found = inventory(folder)
    problems: list[dict] = list(violations())
    rows = []
    seen = set()
    for bank in found["banks"]:
        for op in bank["ops"]:
            if op in seen:
                continue
            seen.add(op)
            status, capability = BINDINGS.get(op, ("unbound", "no binding declared"))
            if op not in BINDINGS:
                problems.append(dict(code="unclassified", detail=op))
            resolved = None
            if status == "registered":
                resolved = _callable(capability)
                if verify and resolved is None:
                    problems.append(dict(code="capability_missing",
                                         detail=f"{op} -> {capability}"))
            rows.append(dict(op=op, phase=bank["phase"], status=status,
                             capability=capability if status == "registered" else None,
                             reason=capability if status != "registered" else None,
                             callable=resolved is not None if status == "registered" else None))
    counts = {status: sum(1 for row in rows if row["status"] == status) for status in STATUSES}
    gated = [row["op"] for row in rows if row["status"] == "requires_grant"]
    return dict(schema="kuhul.phase-ops/1", banks=len(found["banks"]),
                categories=found["categories"], phases=found["phases"],
                total=len(rows), counts=counts, rows=rows, problems=problems,
                gated=gated, execute_gated=[op for op in gated if op in GATED_NAMES],
                authority="declaration_only", executes=False,
                note="a matched pattern grants nothing; a status of requires_grant is the gate")


def summary(report: dict) -> str:
    counts = report["counts"]
    lines = [f"phase operations · {report['banks']} bank(s) · {report['categories']} categor(ies) · "
             f"{report['total']} operation(s)",
             f"  registered      {counts['registered']:2}",
             f"  requires_grant  {counts['requires_grant']:2}  {', '.join(report['gated'])}",
             f"  proposal_only   {counts['proposal_only']:2}",
             f"  unbound         {counts['unbound']:2}"]
    if report["problems"]:
        lines.append("  problems: " + "; ".join(problem["detail"] for problem in report["problems"][:5]))
    lines.append("  (declaration_only · a match grants nothing)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Classify the phase banks' declared operations.")
    parser.add_argument("--folder", default=str(PHASES_DIR))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = classify(Path(args.folder))
    if args.json:
        import json
        print(json.dumps(report, indent=2))
    else:
        print(summary(report))
        for row in report["rows"]:
            if row["status"] != "registered":
                print(f"  {row['status']:14} {row['op']:38} {row['reason']}")
    return 0 if not report["problems"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
