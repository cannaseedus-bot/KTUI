"""Session profiles: the operator contract as a *chat template*, supplied with every request.

A running `llama-server` keeps no chat history between API calls, so the session is the host's job: the
contract, the demonstrations and the runtime context are re-sent with each inference request. This module
owns that template and the experiment that measures whether it helps.

    A_original          the system prompt used before any contract work
    B_contract          the short contract (rules only)
    C_contract_examples the contract plus two demonstrations

Same `plan_graph` validator, same case, same budget for every profile - the only variable is the session.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import evaluation_harness  # noqa: E402
import plan_graph  # noqa: E402
import proposal_eval  # noqa: E402

SCHEMA = "kuhul-session-profiles/v1"
PROFILES = PACKAGE / "data" / "session-profiles.json"
EXPERIMENT = "kuhul-session-experiment/1"
CASES = ("pair-01", "chain-01")


def load(path: Path | None = None) -> dict:
    """Load and validate the profiles: a system prompt and zero or more user/assistant demonstrations."""
    path = Path(path or PROFILES)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, problems=[dict(code="unreadable", detail=str(error))], profiles={})
    problems: list[dict] = []
    if record.get("schema") != SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {SCHEMA}"))
    if record.get("authority") != "declaration_only":
        problems.append(dict(code="authority", detail="a session profile is declaration_only"))
    profiles: dict[str, dict] = {}
    for name, entry in (record.get("profiles") or {}).items():
        system = entry.get("system")
        if system is not None and not str(system).strip():
            problems.append(dict(code="system", detail=f"{name}: empty system prompt"))
        examples = entry.get("examples") or []
        for index, pair in enumerate(examples):
            roles = [message.get("role") for message in pair] if isinstance(pair, list) else []
            if roles != ["user", "assistant"]:
                problems.append(dict(code="example",
                                     detail=f"{name}#{index}: expected user then assistant, got {roles}"))
                continue
            for message in pair:
                if not str(message.get("content") or "").strip():
                    problems.append(dict(code="example", detail=f"{name}#{index}: empty content"))
        profiles[name] = dict(system=system, examples=examples, note=entry.get("note"))
    if len(profiles) < 3:
        problems.append(dict(code="profiles", detail="expected at least three profiles"))
    return dict(ok=not problems, problems=problems, profiles=profiles,
                contract_uri=record.get("contract_uri"), note=record.get("note"))


def profile_digest(profile: dict) -> str:
    """A digest of the whole template, so a verdict can be reproduced from the profile alone."""
    import hashlib
    payload = json.dumps(dict(system=profile.get("system"), examples=profile.get("examples")),
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def messages(profile: dict, task: str) -> list[dict]:
    """The complete message list for one request: system, demonstrations, then the task."""
    built: list[dict] = []
    if profile.get("system"):
        built.append({"role": "system", "content": profile["system"]})
    else:
        # A_original still needs the pre-contract system prompt, which lives in the evaluator.
        built.append({"role": "system", "content": proposal_eval.SYSTEM})
    for pair in profile.get("examples") or []:
        built.extend(dict(message) for message in pair)
    built.append({"role": "user", "content": task})
    return built


def complete(base_url: str, *, max_tokens: int = 900, timeout: int = 420):
    """A completer over a full message list, so the session travels with the request."""
    def run(conversation: list[dict]) -> dict:
        payload = json.dumps({"messages": conversation, "temperature": 0,
                              "max_tokens": max_tokens}).encode("utf-8")
        request = urllib.request.Request(f"{base_url}/chat/completions", data=payload,
                                         headers={"Content-Type": "application/json"})
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=timeout) as response:
            document = json.loads(response.read().decode("utf-8", "replace"))
        latency = int(round((time.monotonic() - started) * 1000))
        choice = (document.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = document.get("usage") or {}
        return dict(text=message.get("content") or "", model=document.get("model") or base_url,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    reasoning_tokens=(usage.get("completion_tokens_details") or {}).get(
                        "reasoning_tokens"),
                    finish_reason=choice.get("finish_reason"), latency_ms=latency)
    return run


def run(model: str, corpus: dict, *, profiles: dict | None = None, repeats: int = 1,
        complete_for=None) -> dict:
    """Every profile against the same cases, scored by the same validator."""
    profiles = profiles or load()
    if not profiles["ok"]:
        raise RuntimeError(f"the session profiles do not load: {profiles['problems']}")
    results: dict[str, dict] = {}
    for name, profile in profiles["profiles"].items():
        results[name] = {}
        for case_id in CASES:
            case = corpus["by_id"].get(case_id)
            if case is None:
                raise KeyError(f"the corpus has no case {case_id!r}")
            cells = []
            for index in range(max(1, int(repeats))):
                conversation = messages(profile, case["input"])
                try:
                    reply = complete_for(conversation)
                    score = evaluation_harness.score_case(case, reply)
                    cells.append(dict(run=index, case=case_id, parsed=score["parsed"],
                                      verdict=score["verdict"], complete=score["complete"],
                                      phase_ok=score.get("phase_ok"),
                                      targets_ok=score.get("targets_ok"),
                                      nodes_ok=score.get("nodes_ok"),
                                      edges_ok=score.get("edges_ok"),
                                      reply_text=(reply.get("text") or "")[:4000],
                                      proposed=score["proposed"],
                                      tokens=(score.get("tokens") or {}).get("total"),
                                      latency_ms=score.get("latency_ms"),
                                      finish_reason=score.get("finish_reason"),
                                      errors=score["errors"]))
                except Exception as error:
                    cells.append(dict(run=index, case=case_id, parsed=False, complete=False,
                                      error=f"{type(error).__name__}: {error}"[:160]))
            completed = [cell for cell in cells if cell.get("complete")]
            results[name][case_id] = dict(
                case=case_id, repeats=len(cells), complete=len(completed),
                phase_ok=sum(1 for cell in cells if cell.get("phase_ok") is True),
                targets_ok=sum(1 for cell in cells if cell.get("targets_ok") is True),
                graph_ok=sum(1 for cell in cells if cell.get("verdict") == "exact"),
                rate=(len(completed) / len(cells)) if cells else None,
                verdicts=_histogram(cells), messages=len(messages(profile, case["input"])),
                cells=cells)
    return dict(schema=EXPERIMENT, model=model, cases=list(CASES), repeats=int(repeats),
                profiles={name: dict(note=profile.get("note"),
                                     examples=len(profile.get("examples") or []),
                                     profile_sha256=profile_digest(profile))
                          for name, profile in profiles["profiles"].items()},
                contract_uri=profiles.get("contract_uri"),
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                results=results, authority="declaration_only", execution=False,
                note=("the session is the only variable; validator, case, budget and settings are "
                      "identical across profiles"))


def _histogram(cells: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for cell in cells:
        key = str(cell.get("verdict") or cell.get("error") or "unparsed")
        counts[key] = counts.get(key, 0) + 1
    return counts


def summary(report: dict) -> str:
    lines = [f"sessions · model {report['model']} · {report['repeats']} repeat(s) · "
             f"cases {', '.join(report['cases'])}"]
    header = "  " + "profile".ljust(22) + "".join(case.ljust(22) for case in report["cases"])
    lines.append(header)
    for name, cases in report["results"].items():
        cells = "".join(f"{cases[case]['complete']}/{cases[case]['repeats']} complete".ljust(22)
                        for case in report["cases"])
        lines.append("  " + name.ljust(22) + cells)
    for name, cases in report["results"].items():
        for case, cell in cases.items():
            lines.append(f"  {name:20} {case:9} {cell['verdicts']} · {cell['messages']} message(s)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    import model_lifecycle

    parser = argparse.ArgumentParser(description="Contract vs contract+examples, on the same validator.")
    parser.add_argument("--model", default="planner")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out", default=str(PACKAGE / "data" / "session-experiment.json"))
    args = parser.parse_args(argv)
    corpus = evaluation_harness.load()
    declaration = model_lifecycle.load()
    entry = declaration["by_name"].get(args.model)
    if entry is None:
        print(f"unknown backend {args.model!r}")
        return 2
    report = run(args.model, corpus, repeats=args.repeats,
                 complete_for=complete(entry["base_url"]))
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(summary(report))
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
