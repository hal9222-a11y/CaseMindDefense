from __future__ import annotations

import logging
import re

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk
from app.services.embedding_service import (
    cosine_similarity,
    deserialize_embedding,
    embed_text,
    embedding_model_name,
)
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
    chunks = session.exec(select(EvidenceChunk)).all()
    evidence_cache: dict[int, Evidence | None] = {}
    results: list[dict] = []

    for chunk in chunks:
        if allowed is not None and chunk.evidence_id not in allowed:
            continue

        # same dimension does not mean same vector space (MiniLM and e5 are
        # both 384-d) - compare by recorded model and require a reindex
        if chunk.embedding_model and chunk.embedding_model != current_model:
            logger.warning(
                "Skipping chunk embedded with a different model "
                "(chunk_id=%s model=%s current=%s) - reindex the evidence",
                chunk.id, chunk.embedding_model, current_model,
            )
            continue

        chunk_embedding = deserialize_embedding(chunk.embedding or "")

        if len(chunk_embedding) != len(query_embedding):
            logger.warning(
                "Skipping chunk with embedding dimension mismatch: "
                "chunk_id=%s evidence_id=%s query_dim=%s chunk_dim=%s",
                chunk.id,
                chunk.evidence_id,
                len(query_embedding),
                len(chunk_embedding),
            )
            continue

        score = cosine_similarity(query_embedding, chunk_embedding)

        if score <= 0:
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
                "score": round(float(score), 6),
                "text": chunk.text,
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]
