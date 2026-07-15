from __future__ import annotations

import logging
import re

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk
from app.services import search_index
from app.services.embedding_service import embed_text, embedding_model_name
from app.services.scope import case_evidence_ids


logger = logging.getLogger(__name__)

# A phone number, ID or plate is an exact string, not a meaning. Embeddings
# cannot match one: they return the nearest vectors no matter how far away, so
# searching 0524657474 produced ten confident-looking hits at ~0.82 for a number
# that is not in the evidence at all. In an evidence tool that is not a poor
# result, it is a false one — an investigator could conclude the number appears
# in the material. Identifier queries are matched literally instead.
IDENTIFIER_RE = re.compile(r"^[\d\s\-+()]{6,}$")


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _exact_identifier_search(
    session: Session, query: str, limit: int, allowed: set[int] | None
) -> list[dict]:
    """Literal match on the digits, so 052-465-7474 and 0524657474 are the same
    number. Returns only real occurrences — an empty list means it is not there."""
    needle = _digits(query)
    evidence_cache: dict[int, Evidence | None] = {}
    results: list[dict] = []

    for chunk in session.exec(select(EvidenceChunk)).all():
        if allowed is not None and chunk.evidence_id not in allowed:
            continue
        text = chunk.text or ""
        if needle not in _digits(text):
            continue
        if chunk.evidence_id not in evidence_cache:
            evidence_cache[chunk.evidence_id] = session.get(Evidence, chunk.evidence_id)
        evidence = evidence_cache[chunk.evidence_id]
        results.append(
            {
                "evidence_id": chunk.evidence_id,
                "filename": evidence.filename if evidence else None,
                "chunk_index": chunk.chunk_index,
                "source_location": chunk.source_location,
                "score": 1.0,  # an exact match is exact; no similarity to report
                "text": text,
                "match": "exact",
            }
        )
        if len(results) >= limit:
            break
    return results


def semantic_search(
    session: Session, query: str, limit: int = 10, case_id: int | None = None
) -> list[dict]:
    query = (query or "").strip()

    if not query:
        return []

    if IDENTIFIER_RE.match(query) and len(_digits(query)) >= 6:
        return _exact_identifier_search(
            session, query, limit, case_evidence_ids(session, case_id)
        )

    query_embedding = embed_text(query, kind="query")

    if not query_embedding:
        return []

    allowed = case_evidence_ids(session, case_id)
    current_model = embedding_model_name()

    # the cached NumPy index scores every chunk in one matrix-vector product and
    # returns only the top-k ids; we then fetch text + filename for just those.
    # (The old path deserialized every embedding string on every query.)
    hits = search_index.search(session, query_embedding, current_model, allowed, limit)
    if not hits:
        return []

    chunk_texts = {
        c.id: c.text
        for c in session.exec(
            select(EvidenceChunk).where(
                EvidenceChunk.id.in_([h["chunk_id"] for h in hits])
            )
        ).all()
    }
    evidence_cache: dict[int, Evidence | None] = {}
    results: list[dict] = []
    for hit in hits:
        ev_id = hit["evidence_id"]
        if ev_id not in evidence_cache:
            evidence_cache[ev_id] = session.get(Evidence, ev_id)
        evidence = evidence_cache[ev_id]
        results.append(
            {
                "evidence_id": ev_id,
                "filename": evidence.filename if evidence else None,
                "chunk_index": hit["chunk_index"],
                "source_location": hit["source_location"],
                "score": hit["score"],
                "text": chunk_texts.get(hit["chunk_id"]),
            }
        )
    return results
