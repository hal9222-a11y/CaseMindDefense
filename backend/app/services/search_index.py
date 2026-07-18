"""In-memory vector index for semantic search.

The old path loaded EVERY chunk on EVERY query, split each stored embedding
string into 384 floats in Python, and summed a dot product in a Python loop.
At a few thousand chunks that is tolerable; a full case (transcriptions + UFDR
chats) runs to hundreds of thousands, and each query would parse tens of
millions of floats — seconds per search.

Instead we parse the embeddings ONCE into a NumPy matrix and cache it, then a
query is a single matrix–vector product. The cache is keyed by a cheap
signature (row count + max id) so it rebuilds automatically after any indexing
or deletion, with no manual invalidation.

ponytail: a process-local dense matrix, rebuilt in full when the signature
changes. Fine to hundreds of thousands of chunks; past that (or for multiple
worker processes) switch to a real ANN index (sqlite-vec / hnswlib)."""
from __future__ import annotations

import threading

import numpy as np
from sqlmodel import Session, func, select

from app.models.evidence import EvidenceChunk
from app.services.embedding_service import deserialize_embedding

_lock = threading.Lock()
_cache: dict = {
    "signature": None,
    "matrix": None,        # (N, D) float32, rows already L2-normalized on store
    "chunk_id": None,
    "evidence_id": None,   # (N,) int64
    "chunk_index": None,   # list[int]
    "source_location": None,  # list[str]
    "model": None,         # list[str]
}


def _signature(session: Session) -> tuple[int, int]:
    count = session.exec(select(func.count()).select_from(EvidenceChunk)).one()
    max_id = session.exec(select(func.max(EvidenceChunk.id))).one() or 0
    return (int(count), int(max_id))


def _rebuild(session: Session, signature: tuple[int, int]) -> None:
    rows = session.exec(
        select(
            EvidenceChunk.id,
            EvidenceChunk.evidence_id,
            EvidenceChunk.chunk_index,
            EvidenceChunk.source_location,
            EvidenceChunk.embedding,
            EvidenceChunk.embedding_model,
        )
    ).all()

    vectors: list[np.ndarray] = []
    chunk_id: list[int] = []
    evidence_id: list[int] = []
    chunk_index: list[int] = []
    source_location: list[str] = []
    model: list[str] = []
    dim: int | None = None

    for cid, ev_id, idx, loc, emb, emb_model in rows:
        vec = deserialize_embedding(emb or "")
        if not vec:
            continue
        if dim is None:
            dim = len(vec)
        if len(vec) != dim:
            # a chunk from a different-dimension model — skip (it needs a
            # reindex anyway; the old path skipped it too)
            continue
        vectors.append(np.asarray(vec, dtype=np.float32))
        chunk_id.append(cid)
        evidence_id.append(ev_id)
        chunk_index.append(idx)
        source_location.append(loc)
        model.append(emb_model or "")

    matrix = np.vstack(vectors) if vectors else np.zeros((0, dim or 1), dtype=np.float32)
    _cache.update({
        "signature": signature,
        "matrix": matrix,
        "chunk_id": np.asarray(chunk_id, dtype=np.int64),
        "evidence_id": np.asarray(evidence_id, dtype=np.int64),
        "chunk_index": chunk_index,
        "source_location": source_location,
        "model": model,
    })


def invalidate() -> None:
    """Force a rebuild on the next search. The (count, max_id) signature can miss
    a change: SQLite REUSES rowids after the max id is deleted (no AUTOINCREMENT),
    so reindexing the top block of chunks into the same count yields an identical
    signature with different vectors — stale hits. Every chunk write calls this."""
    _cache["signature"] = None


def _ensure_fresh(session: Session) -> None:
    signature = _signature(session)
    if _cache["signature"] != signature:
        with _lock:
            if _cache["signature"] != signature:  # re-check inside the lock
                _rebuild(session, signature)


def search(
    session: Session,
    query_vec: list[float],
    current_model: str,
    allowed: set[int] | None,
    limit: int,
) -> list[dict]:
    """Top-`limit` chunks by cosine to query_vec, honoring the case scope
    (`allowed`) and skipping chunks embedded with a different model. Returns
    rows without text — the caller fetches text for just the winners."""
    if not query_vec:
        return []
    _ensure_fresh(session)

    matrix = _cache["matrix"]
    if matrix is None or matrix.shape[0] == 0:
        return []

    q = np.asarray(query_vec, dtype=np.float32)
    if q.shape[0] != matrix.shape[1]:
        return []  # query embedded at a different dimension — nothing comparable

    evidence_id = _cache["evidence_id"]
    model = _cache["model"]

    # boolean mask: right model, and inside the case scope
    mask = np.fromiter((m == current_model for m in model), dtype=bool, count=len(model))
    if allowed is not None:
        mask &= np.isin(evidence_id, np.asarray(list(allowed), dtype=np.int64))
    if not mask.any():
        return []

    # cosine == dot product (rows and query are L2-normalized)
    scores = matrix @ q
    scores = np.where(mask, scores, -np.inf)

    k = min(limit, int(mask.sum()))
    if k <= 0:
        return []
    # argpartition for the top-k, then sort just those
    top = np.argpartition(-scores, k - 1)[:k]
    top = top[np.argsort(-scores[top])]

    results = []
    for i in top:
        score = float(scores[i])
        if score <= 0:
            continue
        results.append({
            "chunk_id": int(_cache["chunk_id"][i]),
            "evidence_id": int(evidence_id[i]),
            "chunk_index": _cache["chunk_index"][i],
            "source_location": _cache["source_location"][i],
            "score": round(score, 6),
        })
    return results
