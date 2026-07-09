from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk
from app.services.embedding_service import cosine_similarity, deserialize_embedding, embed_text


logger = logging.getLogger(__name__)


def semantic_search(session: Session, query: str, limit: int = 10) -> list[dict]:
    query = (query or "").strip()

    if not query:
        return []

    query_embedding = embed_text(query)

    if not query_embedding:
        return []

    chunks = session.exec(select(EvidenceChunk)).all()
    evidence_cache: dict[int, Evidence | None] = {}
    results: list[dict] = []

    for chunk in chunks:
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
