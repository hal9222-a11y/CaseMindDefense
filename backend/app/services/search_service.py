from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk


def search_chunks(session: Session, q: str, limit: int = 10) -> list[dict]:
    query = (q or "").strip()
    if not query:
        return []
    # ponytail: LIKE substring match in SQL (ASCII case-insensitive, fine for
    # Hebrew which has no case); switch to FTS5 when ranking/scale matters
    rows = session.exec(
        select(EvidenceChunk, Evidence)
        .join(Evidence, Evidence.id == EvidenceChunk.evidence_id)
        .where(EvidenceChunk.text.contains(query))  # type: ignore[attr-defined]
        .limit(limit)
    ).all()
    return [
        {
            "evidence_id": chunk.evidence_id,
            "filename": evidence.filename,
            "chunk_index": chunk.chunk_index,
            "source_location": chunk.source_location,
            "score": 1.0,
            "text": chunk.text,
        }
        for chunk, evidence in rows
    ]
