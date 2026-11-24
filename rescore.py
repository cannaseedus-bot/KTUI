"""Offline re-scoring: derive a new scoring artifact from stored replies, without new inference.

The rule the review set: the original evidence stays immutable, and a derived artifact must say what it was
derived from and by which scorer. So every result carries

    source            the artifact file name and its sha256
    scorer            the scoring contract version used
    reply_digest      sha256 of the reply text that was scored, when the reply was stored

A stored artifact that kept only a 240-character head cannot be re-scored for phase or targets: the reply is
truncated, and this returns `replies_unavailable` rather than guessing from the head. In that case the honest
move is a **new execution** of the frozen protocol, labelled as such - which is what `contract_experiment`
produces.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
for _candidate in (str(HOST_ROOT / "kuhul-phase-engine-v0.1.0" / "core"), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import evaluation_harness  # noqa: E402

SCHEMA = "kuhul://evaluation/rescore/v1"
SCORER = "kuhul://evaluation/scoring/v1"
DATA = HOST_ROOT / "kuhul-phase-engine-v0.1.0" / "data"


def file_digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reply_digest(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def replies_of(artifact: dict) -> dict:
    """Every stored reply, keyed by (model, condition, run) - full text only, never a head."""
    found = {}
    for model, conditions in (artifact.get("results") or {}).items():
        for condition, block in (conditions or {}).items():
            for cell in (block or {}).get("cells") or []:
                key = (model, condition, int(cell.get("run", 0)))
                text = cell.get("reply_text")
                found[key] = dict(text=text, head=cell.get("reply_head"),
                                  truncated=text is None or (text is not None and len(text) == 4000))
    return found


def availability(artifact: dict) -> dict:
    """Can this artifact be re-scored? Only if the full replies were kept."""
    replies = replies_of(artifact)
    full = [key for key, entry in replies.items() if entry["text"]]
    return dict(total=len(replies), full=len(full),
                rescoreable=bool(full) and len(full) == len(replies),
                missing=len(replies) - len(full))


def rescore(artifact_path: Path, corpus: dict, *, write: bool = False) -> dict:
    """Re-score every stored reply with the current scorer and report the derived artifact."""
    artifact_path = Path(artifact_path)
    if not artifact_path.is_file():
        return dict(ok=False, refused="artifact_missing", detail=str(artifact_path))
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    status = availability(artifact)
    base = dict(schema=SCHEMA, source=artifact_path.name,
                source_sha256=file_digest(artifact_path), scorer=SCORER,
                availability=status, authority="evaluation_only", execution=False)
    if not status["rescoreable"]:
        return dict(base, ok=False, refused="replies_unavailable",
                    detail=("the artifact stored reply heads, not replies; phase and target scores cannot be "
                            "recovered - run the frozen protocol again and label it a new execution"),
                    scores=[])
    case = corpus["by_id"].get(artifact.get("case"))
    if case is None:
        return dict(base, ok=False, refused="case_not_in_corpus", detail=str(artifact.get("case")))
    scores = []
    for (model, condition, run), entry in sorted(replies_of(artifact).items()):
        reply = dict(text=entry["text"], model=model, latency_ms=None, completion_tokens=None)
        score = evaluation_harness.score_case(case, reply)
        scores.append(dict(model=model, condition=condition, run=run,
                           reply_digest=reply_digest(entry["text"]),
                           parsed=score["parsed"], verdict=score["verdict"],
                           complete=score["complete"], nodes_ok=score["nodes_ok"],
                           edges_ok=score["edges_ok"], phase_ok=score.get("phase_ok"),
                           targets_ok=score.get("targets_ok"), errors=score["errors"]))
    derived = dict(base, ok=True, refused=None, case=artifact.get("case"), scores=scores,
                   summary=_summary(scores))
    if write:
        out = DATA / f"{artifact_path.stem}.rescored.json"
        out.write_text(json.dumps(derived, indent=2) + "\n", encoding="utf-8")
        derived["written"] = out.name
    return derived


def _summary(scores: list[dict]) -> dict:
    groups: dict[str, dict] = {}
    for score in scores:
        key = f"{score['model']}/{score['condition']}"
        block = groups.setdefault(key, dict(replies=0, parsed=0, complete=0, graph=0,
                                            phase_ok=0, targets_ok=0, verdicts={}))
        block["replies"] += 1
        block["parsed"] += int(bool(score["parsed"]))
        block["complete"] += int(bool(score["complete"]))
        block["graph"] += int(score.get("verdict") == "exact")
        block["phase_ok"] += int(score.get("phase_ok") is True)
        block["targets_ok"] += int(score.get("targets_ok") is True)
        verdict = str(score.get("verdict") or "unparsed")
        block["verdicts"][verdict] = block["verdicts"].get(verdict, 0) + 1
    return groups


def summary(report: dict) -> str:
    if not report.get("ok"):
        return (f"rescore · {report.get('source')} · REFUSED: {report.get('refused')}\n"
                f"  {report.get('detail', '')}")
    lines = [f"rescore · {report['source']} ({report['availability']['full']} replies) · "
             f"scorer {report['scorer']}"]
    for key, block in report["summary"].items():
        lines.append(f"  {key:34} complete {block['complete']} graph {block['graph']} "
                     f"phase {block['phase_ok']} targets {block['targets_ok']} · {block['verdicts']}")
    return "\n".join(lines)
