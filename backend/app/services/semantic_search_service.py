from sqlmodel import Session, select
from app.models.evidence import Evidence, EvidenceChunk
from app.services.embedding_service import cosine_similarity, deserialize_embedding, embed_text

def semantic_search(session: Session, query: str, limit: int = 10) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    query_embedding = embed_text(query)
    chunks = session.exec(select(EvidenceChunk)).all()
    results = []
    for chunk in chunks:
        score = cosine_similarity(query_embedding, deserialize_embedding(chunk.embedding or ""))
        if score <= 0:
            continue
        evidence = session.get(Evidence, chunk.evidence_id)
        results.append({"evidence_id": chunk.evidence_id, "filename": evidence.filename if evidence else None, "chunk_index": chunk.chunk_index, "source_location": chunk.source_location, "score": round(float(score), 6), "text": chunk.text})
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]
