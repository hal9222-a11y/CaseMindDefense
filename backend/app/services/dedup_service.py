"""Content deduplication: the same conversation imported as both a PDF and a
TXT is two evidence items with different SHA256s, so register-time dedup (which
compares the raw file bytes) never catches it. It then counts twice everywhere
— entities, the graph, the flags, the insights — quietly inflating how central a
person or topic looks.

Two signals, both offline:
  exact   — identical normalized text (same content, different container)
  near    — high cosine between the items' mean chunk-embeddings (OCR wobble,
            an extra header, a re-export)

Nothing is deleted here; this reports groups for the user to review and then
delete the redundant copy. Deleting evidence is destructive and stays a
deliberate human action."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk
from app.services.embedding_service import cosine_similarity, deserialize_embedding

NEAR_DUPLICATE_MIN = 0.97   # mean-embedding cosine; deliberately high — a near
                            # match must be the SAME material, not the same topic
MIN_CHARS = 40              # ignore near-empty items (an icon's OCR) — they all
                            # look alike and are not meaningful duplicates
_WS = re.compile(r"\s+")
# directional/zero-width marks carry no content. Whisper renders silent or
# music-only audio as a RUN of RLM/LRM marks (‎/‏); left in, dozens of
# such failed transcriptions hash identical and look like one big duplicate
# group. Strip them so those items fall below MIN_CHARS and drop out.
_INVISIBLE = re.compile(
    "[​-‏"   # zero-width space..RLM (incl. LRM/RLM)
    "‪-‮"    # bidi embeddings / overrides
    "⁠﻿�]"  # word-joiner, BOM/ZWNBSP, replacement char
)


def _normalized_text(chunks: list[EvidenceChunk]) -> str:
    joined = "\n".join(c.text or "" for c in sorted(chunks, key=lambda c: c.chunk_index))
    return _WS.sub(" ", _INVISIBLE.sub("", joined)).strip().lower()


def _mean_embedding(chunks: list[EvidenceChunk]) -> list[float] | None:
    vecs = [deserialize_embedding(c.embedding or "") for c in chunks if c.embedding]
    vecs = [v for v in vecs if v]
    if not vecs:
        return None
    dim = len(vecs[0])
    if any(len(v) != dim for v in vecs):
        return None
    return [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]


def find_duplicates(session: Session, case_id: int | None = None) -> list[dict]:
    """Groups of evidence that carry the same content. Each group: the reason
    (exact/near), a similarity, and the members (id, filename) — most-similar
    groups first. Exact groups come first (certainty over guess)."""
    from app.services.scope import case_evidence_ids

    allowed = case_evidence_ids(session, case_id)

    chunks_by_ev: dict[int, list[EvidenceChunk]] = defaultdict(list)
    for chunk in session.exec(select(EvidenceChunk)).all():
        if allowed is None or chunk.evidence_id in allowed:
            chunks_by_ev[chunk.evidence_id].append(chunk)
    if not chunks_by_ev:
        return []

    filenames = {
        eid: fn for eid, fn in session.exec(select(Evidence.id, Evidence.filename)).all()
    }

    norm: dict[int, str] = {}
    means: dict[int, list[float]] = {}
    for ev_id, chunks in chunks_by_ev.items():
        text = _normalized_text(chunks)
        if len(text) < MIN_CHARS:
            continue
        norm[ev_id] = text
        mean = _mean_embedding(chunks)
        if mean:
            means[ev_id] = mean

    groups: list[dict] = []
    consumed: set[int] = set()

    # 1) exact: bucket by hash of normalized text
    by_hash: dict[str, list[int]] = defaultdict(list)
    for ev_id, text in norm.items():
        by_hash[hashlib.sha256(text.encode("utf-8")).hexdigest()].append(ev_id)
    for members in by_hash.values():
        if len(members) > 1:
            consumed.update(members)
            groups.append({
                "reason": "exact",
                "similarity": 1.0,
                "members": [{"id": m, "filename": filenames.get(m)} for m in sorted(members)],
            })

    # 2) near: pairwise cosine over the remaining items' mean embeddings.
    # O(n^2) over EVIDENCE count (not chunks) — fine at case scale; the exact
    # pass already removed the identical ones.
    # ponytail: quadratic over evidence; if a case grows past a few thousand
    # items, block by a coarse key (length bucket) or use an ANN index first.
    candidates = [e for e in means if e not in consumed]
    adjacency: dict[int, set[int]] = defaultdict(set)
    best: dict[frozenset[int], float] = {}
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            score = cosine_similarity(means[a], means[b])
            if score >= NEAR_DUPLICATE_MIN:
                adjacency[a].add(b)
                adjacency[b].add(a)
                best[frozenset((a, b))] = score

    # connected components of the near-duplicate graph
    seen: set[int] = set()
    for start in list(adjacency):
        if start in seen:
            continue
        stack, comp = [start], []
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            comp.append(node)
            stack.extend(adjacency[node] - seen)
        if len(comp) > 1:
            sims = [best[fs] for fs in best if set(fs) <= set(comp)]
            groups.append({
                "reason": "near",
                "similarity": round(min(sims), 4) if sims else NEAR_DUPLICATE_MIN,
                "members": [{"id": m, "filename": filenames.get(m)} for m in sorted(comp)],
            })

    groups.sort(key=lambda g: (g["reason"] != "exact", -g["similarity"]))
    return groups
