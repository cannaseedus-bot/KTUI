"""Can the small model produce valid K'UHUL plans as reliably as the large one? Measure it.

The harness asks a backend to translate an instruction into an operator plan, then scores the plan with
the validators that already exist (`proposal.validate_all`), not with a fluency judgement:

    schema-valid proposals      does it follow the constrained vocabulary?
    correct operator ordering   does `next` actually chain filter -> map -> fold -> reduce?
    correct URI bindings        are targets registered references?
    authority violations        did it claim something other than `proposal`?
    tokens and latency          what did it cost, as reported by the server
    repeated-run consistency    same instruction, same plan, three times?

Two honesty rules: a reply that cannot be parsed is scored as `unparseable`, never as a zero-quality plan;
and a metric nobody measured is `None`, never 0.

No model is called unless a `complete` callable is supplied, so the scoring logic is testable without a
server, and the live comparison is an explicit, separate step.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import model_router  # noqa: E402
import plan_graph  # noqa: E402
import proposal  # noqa: E402

SCHEMA = "kuhul-proposal-eval/1"
FIELDS = ("phase", "operator", "target", "binding", "next", "authority")

# Instruction -> the operator order a correct plan walks. Kept short and vocabulary-only so the task is a
# test of the grammar, not of world knowledge.
TASKS = (
    dict(id="filter_map", instruction="Keep the valid matches, then transform each one.",
         expect=["filter", "map"], target="graph.matches", binding="valid"),
    dict(id="full_chain",
         instruction="Retrieve valid graph matches, transform them into propositions, accumulate "
                     "evidence, and reduce the result.",
         # "accumulate evidence" is legitimately fold OR accumulate - the review calls accumulate the
         # fold's state update - so the task accepts either rather than pinning one phrasing.
         expect=["filter", "map", "fold", "reduce"],
         target="graph.matches", binding="valid"),
    dict(id="fold_only", instruction="Combine the collected propositions into one accumulator.",
         expect=["fold"], target="proposition.v1", binding=None),
    dict(id="reduce_only", instruction="Collapse the ranked candidates to a single selected score.",
         expect=["reduce"], target="graph.matches", binding=None),
)

SYSTEM = (
    "You translate instructions into K'UHUL operator plans. Reply with a JSON array and NOTHING else - "
    "no prose, no explanation, no code fence. "
    "Each element has exactly these keys: phase (one of Pop, Wo, Yax, Sek, Ch'en, Xul), operator (one of "
    "filter, map, fold, accumulate, reduce), target (a reference like \"graph.matches\" or "
    "\"gml://relations\"), binding (a string, required for filter and map), next (the next operator or "
    "phase, or null), authority (the string \"proposal\"). Every plan uses phase \"Sek\"."
)


def _extract(text: str) -> list | None:
    """Pull the JSON array out of a reply, tolerating fences and prose around it."""
    body = str(text or "").strip()
    body = re.sub(r"^```(?:json)?|```$", "", body, flags=re.M).strip()
    for opening, closing in (("[", "]"), ("{", "}")):
        start, end = body.find(opening), body.rfind(closing)
        if start != -1 and end > start:
            try:
                parsed = json.loads(body[start:end + 1])
            except json.JSONDecodeError:
                continue
            return parsed if isinstance(parsed, list) else [parsed]
    return None


def live_complete(base_url: str, *, system: str = SYSTEM, timeout: int = 120):
    """A `complete(prompt)` bound to one llama-server, reporting tokens from the server's usage field."""
    def complete(prompt: str) -> dict:
        # A plan is a handful of objects: 220 tokens is generous, and an unbounded budget lets a small
        # model ramble for minutes at ~5 tokens/s instead of answering.
        payload = json.dumps({"messages": [{"role": "system", "content": system},
                                           {"role": "user", "content": prompt}],
                              "temperature": 0, "max_tokens": 900}).encode("utf-8")
        request = urllib.request.Request(f"{base_url}/chat/completions", data=payload,
                                         headers={"Content-Type": "application/json"})
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=timeout) as response:
            document = json.loads(response.read().decode("utf-8", "replace"))
        latency = int(round((time.monotonic() - started) * 1000))
        choice = (document.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = document.get("usage") or {}
        return dict(text=message.get("content") or "",
                    model=document.get("model") or base_url,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    reasoning_tokens=(usage.get("completion_tokens_details") or {}).get(
                        "reasoning_tokens"),
                    finish_reason=choice.get("finish_reason"),
                    latency_ms=latency)
    return complete


def score_plan(reply: dict, task: dict) -> dict:
    """Score one reply two ways: as node proposals (graph) and as six-field proposals (validators).

    A reply may name operators without edges - `{"phase": "Sek", "operators": [...]}` - which is the
    smaller prediction problem the review proposed. The host resolves edges; it does not repair the plan.
    """
    completion = reply.get("completion_tokens")
    reasoning = reply.get("reasoning_tokens")
    tokens = dict(total=completion if isinstance(completion, int) else None,
                  reasoning=reasoning if isinstance(reasoning, int) else None,
                  final_json=(completion - reasoning
                              if isinstance(completion, int) and isinstance(reasoning, int) else None))
    sequence = plan_graph.parse_sequence(reply.get("text"))
    graph_score = plan_graph.compare(sequence, expected=task["expect"]) if sequence else None
    if graph_score is not None:
        return dict(task=task["id"], model=reply.get("model"), latency_ms=reply.get("latency_ms"),
                    prompt_tokens=reply.get("prompt_tokens"), completion_tokens=completion,
                    tokens=tokens, parsed=True, form="sequence",
                    proposals=[sequence], valid=1 if graph_score["nodes_ok"] else 0,
                    invalid=0 if graph_score["nodes_ok"] else 1,
                    operators=graph_score["proposed"], nodes_ok=graph_score["nodes_ok"],
                    edges_ok=graph_score["edges_ok"], order_ok=graph_score["edges_ok"],
                    verdict=graph_score["verdict"],
                    extra_operators=graph_score["extra_operators"],
                    missing_operators=graph_score["missing_operators"],
                    misplaced_accumulate=graph_score["misplaced_accumulate"],
                    authority_ok=graph_score["authority_ok"], binding_ok=None,
                    errors=([graph_score["verdict"]] if graph_score["verdict"] != "exact" else []))
    proposals = _extract(reply.get("text"))
    result = dict(task=task["id"], model=reply.get("model"), latency_ms=reply.get("latency_ms"),
                  prompt_tokens=reply.get("prompt_tokens"), completion_tokens=completion,
                  tokens=tokens, parsed=proposals is not None, form="fields", proposals=[],
                  valid=0, invalid=0, order_ok=None, nodes_ok=None, edges_ok=None, verdict=None,
                  extra_operators=[], missing_operators=[], misplaced_accumulate=[],
                  binding_ok=None, authority_ok=None, errors=[])
    if proposals is None:
        # Distinguish a budget truncation from a model that answered in prose: the first is our limit,
        # the second is the model's failure, and reporting them the same would mislead the comparison.
        body = str(reply.get("text") or "")
        truncated = ("[" in body and "]" not in body) or reply.get("finish_reason") == "length"
        result["errors"].append("truncated" if truncated else "unparseable")
        result["truncated"] = truncated
        return result
    report = proposal.validate_all(proposals)
    result["proposals"] = [item.get("proposal") if item.get("ok") else None
                           for item in report["results"]]
    result["valid"] = sum(1 for item in report["results"] if item["ok"])
    result["invalid"] = len(report["results"]) - result["valid"]
    result["errors"] = [problem["code"] for problem in report["problems"]]
    operators = [item["proposal"]["operator"] for item in report["results"] if item["ok"]]
    result["operators"] = operators
    expected = [option if isinstance(option, (tuple, list)) else (option,) for option in task["expect"]]
    graph = plan_graph.compare(operators, expected=[option for option in task["expect"]])
    result["nodes_ok"] = graph["nodes_ok"]
    result["edges_ok"] = graph["edges_ok"]
    result["order_ok"] = graph["edges_ok"]
    result["verdict"] = graph["verdict"]
    result["extra_operators"] = graph["extra_operators"]
    result["missing_operators"] = graph["missing_operators"]
    # Measure the *claim*, not only the accepted proposals: asking for "execute" is a violation even
    # though the validator refuses the proposal that carried it.
    claimed = [str(item.get("authority") or "").strip().lower() for item in proposals
               if isinstance(item, dict)]
    result["authority_ok"] = bool(claimed) and all(value in proposal.AUTHORITIES for value in claimed)
    targets = [((item["proposal"] or {}).get("target") or "") for item in report["results"] if item["ok"]]
    result["binding_ok"] = bool(targets) and all(
        target.startswith(("graph.", "gml://", "kuhul://", "aiml://", "⟁")) for target in targets)
    return result


def evaluate(models: dict, *, complete_for, tasks=TASKS, runs: int = 3) -> dict:
    """Run every task against every model `runs` times and aggregate."""
    report = dict(schema=SCHEMA, runs=runs, tasks=[task["id"] for task in tasks], models={})
    for name, complete in complete_for.items():
        scores = []
        for task in tasks:
            for run in range(runs):
                reply = complete(task["instruction"])
                score = score_plan(reply, task)
                score["run"] = run
                scores.append(score)
        parsed = [score for score in scores if score["parsed"]]
        order = [score["order_ok"] for score in parsed if score["order_ok"] is not None]
        tokens = [score["completion_tokens"] for score in scores
                  if isinstance(score.get("completion_tokens"), int)]
        latencies = [score["latency_ms"] for score in scores
                     if isinstance(score.get("latency_ms"), int)]
        consistency = {}
        for task in tasks:
            plans = [json.dumps(score["operators"], sort_keys=True) for score in scores
                     if score["task"] == task["id"] and score["parsed"]]
            consistency[task["id"]] = (len(set(plans)) <= 1) if plans else None
        verdicts: dict[str, int] = {}
        for score in parsed:
            key = str(score.get("verdict") or "undeclared")
            verdicts[key] = verdicts.get(key, 0) + 1
        reasoning = [score.get("tokens", {}).get("reasoning") for score in scores
                     if isinstance((score.get("tokens") or {}).get("reasoning"), int)]
        final_json = [score.get("tokens", {}).get("final_json") for score in scores
                      if isinstance((score.get("tokens") or {}).get("final_json"), int)]
        report["models"][name] = dict(
            model=next((score["model"] for score in scores if score.get("model")), None),
            replies=len(scores), parsed=len(parsed), unparseable=len(scores) - len(parsed),
            truncated=sum(1 for score in scores if score.get("errors") and "truncated" in score["errors"]),
            valid_proposals=sum(score["valid"] for score in scores),
            invalid_proposals=sum(score["invalid"] for score in scores),
            nodes_ok=sum(1 for score in parsed if score.get("nodes_ok")),
            edges_ok=sum(1 for score in parsed if score.get("edges_ok")),
            order_ok=sum(1 for flag in order if flag), order_measured=len(order),
            verdicts=verdicts,
            extra_operators=sum(len(score.get("extra_operators") or []) for score in parsed),
            misplaced_accumulate=sum(1 for score in parsed if score.get("misplaced_accumulate")),
            reasoning_tokens=(sum(reasoning) if reasoning else None),
            final_json_tokens=(sum(final_json) if final_json else None),
            authority_violations=sum(1 for score in parsed if score["authority_ok"] is False),
            binding_ok=sum(1 for score in parsed if score["binding_ok"]), binding_measured=len(parsed),
            consistent=sum(1 for flag in consistency.values() if flag),
            consistency_measured=sum(1 for flag in consistency.values() if flag is not None),
            completion_tokens=(sum(tokens) if tokens else None),
            tokens_measured=bool(tokens),
            latency_mean_ms=(int(round(sum(latencies) / len(latencies))) if latencies else None),
            consistency=consistency, scores=scores)
    report["execution"] = False
    report["authority"] = "declaration_only"
    report["note"] = ("scored with proposal.validate_all; unmeasured metrics are None, not zero. "
                      "A valid plan is still a proposal: nothing here admits or executes")
    return report


def summarise(report: dict) -> str:
    lines = [f"proposal evaluation · {len(report['models'])} model(s) · {len(report['tasks'])} task(s) "
             f"× {report['runs']} run(s)"]
    for name, model in report["models"].items():
        lines.append(f"  {name}")
        lines.append(f"    parsed {model['parsed']}/{model['replies']} · "
                     f"valid {model['valid_proposals']} · invalid {model['invalid_proposals']} · "
                     f"unparseable {model['unparseable']}")
        lines.append(f"    order ok {model['order_ok']}/{model['order_measured']} · "
                     f"bindings ok {model['binding_ok']}/{model['binding_measured']} · "
                     f"authority violations {model['authority_violations']}")
        lines.append(f"    consistent {model['consistent']}/{model['consistency_measured']} · "
                     f"completion tokens {model['completion_tokens'] if model['tokens_measured'] else 'not measured'} · "
                     f"mean latency {model['latency_mean_ms']} ms")
    return "\n".join(lines)
