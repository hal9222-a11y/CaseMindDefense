from sqlmodel import Session, select
from app.models.evidence import Evidence, EvidenceChunk

def search_chunks(session: Session, q: str, limit: int = 10) -> list[dict]:
    query = (q or "").strip().lower()
    if not query:
        return []
    chunks = session.exec(select(EvidenceChunk)).all()
    results = []
    for chunk in chunks:
        if query in (chunk.text or "").lower():
            evidence = session.get(Evidence, chunk.evidence_id)
            results.append({"evidence_id": chunk.evidence_id, "filename": evidence.filename if evidence else None, "chunk_index": chunk.chunk_index, "source_location": chunk.source_location, "score": 1.0, "text": chunk.text})
    return results[:limit]
