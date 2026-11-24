"""Grams-µ: tokens to n-grams, n-grams to candidate relations - and nothing invented in between.

Three responsibilities, kept apart on purpose:

    extraction    which token sequences are candidates   (this module, deterministic)
    embedding     semantic geometry for those sequences  (EmbeddingGemma, when it can supply it)
    relations     whether a typed edge is supported      (GML / Relations-u - NOT this module)

So a bigram is adjacency, never a claim: `black dog` is extracted, and `relation` stays `None` with
`requires: "gml"` until the graph says what it is. The same rule for vectors: if the encoder or the stored
vectors are unavailable, `vectors` is `None` with a reason rather than a fabricated similarity.

Two windowing semantics, because the difference decides the edges:

    sliding   every adjacent n-gram over one span: 5 tokens -> 4 bigrams, 3 trigrams
    bound     five declared positional slots, edges only between neighbours; no cross-slot trigram unless
              the slots declare it, so "five wildcards" cannot silently become a sliding window
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(PACKAGE / "adapters"), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

SCHEMA = "kuhul://micronaut/grams/v1"
VECTORS = HOST_ROOT / "aiml-embeddinggemma2-vectors"
WINDOWS = (1, 2, 3)
TOKEN = re.compile(r"[A-Za-z0-9']+")


class GramError(ValueError):
    """An extraction request that the declaration does not permit."""


def tokens(text: str) -> list[str]:
    """Deterministic tokenisation: word characters only, case preserved for display, folded for keys."""
    return TOKEN.findall(str(text or ""))


def extract(text: str, *, windows=WINDOWS, mode: str = "sliding", slots: int | None = None) -> dict:
    """Extract n-grams with provenance refs. `sliding` and `bound` are different graphs, not options."""
    words = tokens(text)
    if not words:
        return dict(schema=SCHEMA, source=str(text or ""), mode=mode, tokens=[],
                    grams=[], by_size={}, empty=True)
    if mode not in ("sliding", "bound"):
        raise GramError(f"mode {mode!r} is not 'sliding' or 'bound'")
    if mode == "bound":
        if not slots or slots > len(words):
            raise GramError(f"bound mode needs slots <= {len(words)} tokens, got {slots}")
        words = words[:slots]

    grams: list[dict] = []
    for size in sorted({int(window) for window in windows}):
        if size < 1 or size > len(words):
            continue
        if mode == "bound" and size > 2:
            # A positional binding declares unigrams and adjacent pairs; a trigram would need a slot
            # pattern that spans three positions, and inventing that is exactly what this refuses.
            continue
        for start in range(0, len(words) - size + 1):
            span = words[start:start + size]
            grams.append(dict(
                id=f"gram://{'+'.join(part.lower() for part in span)}#{start}-{start + size - 1}",
                size=size, text=" ".join(span), tokens=span,
                start=start, end=start + size - 1, mode=mode,
                parents=[f"gram://{'+'.join(part.lower() for part in words[start:start + size - 1])}"
                         f"#{start}-{start + size - 2}"] if size > 1 else []))
    by_size: dict[str, int] = {}
    for gram in grams:
        by_size[str(gram["size"])] = by_size.get(str(gram["size"]), 0) + 1
    return dict(schema=SCHEMA, source=str(text or ""), mode=mode, tokens=words, grams=grams,
                by_size=dict(sorted(by_size.items())), empty=False,
                authority="declaration_only", execution=False)


def provenance(extraction: dict) -> dict:
    """A digest over the extraction, so a relation candidate can cite exactly what produced it."""
    payload = [[gram["id"], gram["text"], gram["size"]] for gram in extraction.get("grams") or []]
    canonical = json.dumps(dict(tokens=extraction.get("tokens") or [], grams=payload,
                                mode=extraction.get("mode")),
                           sort_keys=True, separators=(",", ":"))
    return dict(schema=SCHEMA, digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                grams=len(payload), mode=extraction.get("mode"))


# -- embedding: a binding to the existing producer, never a substitute for it ---------------------------
def encoder() -> dict:
    """Whether the EmbeddingGemma vectors are present, with the reason when they are not."""
    manifest = VECTORS / "manifest.json"
    if not manifest.is_file():
        return dict(available=False, reason=f"no vector manifest at {manifest}")
    try:
        record = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(available=False, reason=f"unreadable manifest: {error}")
    return dict(available=True, model=record.get("model"), dimensions=record.get("dimensions"),
                rows=record.get("categories"), normalization=record.get("normalization"))


def embed(extraction: dict, *, adapter=None) -> dict:
    """Score gram similarity through the stored vectors, or say why it cannot.

    The stored vectors are AIML patterns, not grams: this returns the encoder's shape and, when an adapter
    is supplied, whatever similarity it computes for the gram text. It never invents a score.
    """
    status = encoder()
    if not status["available"]:
        return dict(schema=SCHEMA, available=False, reason=status["reason"], vectors=None,
                    grams=0, execution=False)
    if adapter is None:
        return dict(schema=SCHEMA, available=False, vectors=None, grams=0, encoder=status,
                    reason=("no adapter supplied: similarity needs an encoder for the gram text, and "
                            "the stored vectors cover AIML patterns instead"),
                    execution=False)
    scores = []
    for gram in extraction.get("grams") or []:
        if gram["size"] < 2:
            continue
        try:
            hits = adapter.for_text(gram["text"], top_k=3)
        except Exception as error:                     # an adapter that fails is not a score of zero
            return dict(schema=SCHEMA, available=False, vectors=None, grams=0,
                        reason=f"{type(error).__name__}: {error}"[:160], execution=False)
        scores.append(dict(gram=gram["id"], text=gram["text"],
                           nearest=[dict(text=hit[0], score=hit[1]) for hit in (hits or [])]))
    return dict(schema=SCHEMA, available=True, encoder=status, vectors=scores,
                grams=len(scores), authority="declaration_only", execution=False)


# -- candidate relations: adjacency, not topology ------------------------------------------------------
def relation_candidates(extraction: dict) -> dict:
    """Pairs worth asking the graph about. `relation` stays None: GML decides whether an edge exists."""
    grams = extraction.get("grams") or []
    bigrams = [gram for gram in grams if gram["size"] == 2]
    trigrams = [gram for gram in grams if gram["size"] == 3]
    candidates = []
    for bigram in bigrams:
        supporting = [trigram["id"] for trigram in trigrams
                      if bigram["start"] in (trigram["start"], trigram["end"] - 1)]
        candidates.append(dict(
            gram=bigram["id"], text=bigram["text"], tokens=bigram["tokens"],
            relation=None, requires="gml", supported_by=supporting,
            note="adjacency only: a typed edge needs the GML graph"))
    return dict(schema=SCHEMA, mode=extraction.get("mode"), candidates=candidates,
                count=len(candidates), unresolved=len(candidates),
                provenance=provenance(extraction),
                authority="declaration_only", execution=False)


def propose(extraction: dict, *, target: str = "graph.matches") -> dict:
    """A K'UHUL proposal for the grams stage: FILTER candidates, MAP to relations, FOLD the evidence."""
    return dict(schema="kuhul://proposal/grams/1", phase="Sek",
                operators=["filter", "map", "fold"], target=target,
                grams=len(extraction.get("grams") or []),
                provenance=provenance(extraction)["digest"],
                authority="proposal", execution=False, admitted=False)


def summary(extraction: dict) -> str:
    if extraction.get("empty"):
        return "grams · no tokens"
    counts = ", ".join(f"{size}-gram {count}" for size, count in extraction["by_size"].items())
    return (f"grams · {len(extraction['tokens'])} token(s) · mode {extraction['mode']} · {counts} · "
            f"{len(extraction['grams'])} gram(s)")
