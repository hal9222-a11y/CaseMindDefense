from sqlmodel import Session
from app.services.semantic_search_service import semantic_search

def answer_with_evidence(session: Session, question: str, limit: int = 5) -> dict:
    question = (question or "").strip()
    if not question:
        return {"answer": "No question provided.", "citations": []}
    results = semantic_search(session=session, query=question, limit=limit)
    if not results:
        return {"answer": "No relevant evidence was found.", "citations": []}
    citations = [{k: item.get(k) for k in ["evidence_id", "filename", "chunk_index", "source_location", "score", "text"]} for item in results]
    lines = ["Relevant evidence was found. Review the cited chunks below.", ""]
    for i, c in enumerate(citations, 1):
        lines.append(f"[{i}] {c['filename']} (Evidence ID: {c['evidence_id']}, Chunk: {c['chunk_index']}, Location: {c['source_location']})")
        lines.append(c["text"] or "")
        lines.append("")
    return {"answer": "\n".join(lines).strip(), "citations": citations}
