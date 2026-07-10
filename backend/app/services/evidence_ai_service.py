from sqlmodel import Session

from app.services import llm_service
from app.services.semantic_search_service import semantic_search

NOT_FOUND_ANSWER = "No relevant evidence was found."


def _citations_only_answer(citations: list[dict]) -> str:
    lines = ["Relevant evidence was found. Review the cited chunks below.", ""]
    for i, c in enumerate(citations, 1):
        lines.append(
            f"[{i}] {c['filename']} (Evidence ID: {c['evidence_id']}, "
            f"Chunk: {c['chunk_index']}, Location: {c['source_location']})"
        )
        lines.append(c["text"] or "")
        lines.append("")
    return "\n".join(lines).strip()


def answer_with_evidence(session: Session, question: str, limit: int = 5) -> dict:
    question = (question or "").strip()
    if not question:
        return {"answer": "No question provided.", "citations": [], "mode": "none"}

    results = semantic_search(session=session, query=question, limit=limit)
    if not results:
        return {"answer": NOT_FOUND_ANSWER, "citations": [], "mode": "none"}

    citations = [
        {k: item.get(k) for k in ["evidence_id", "filename", "chunk_index", "source_location", "score", "text"]}
        for item in results
    ]

    llm_answer = None
    if llm_service.ollama_available():
        llm_answer = llm_service.synthesize_answer(question, citations)

    if llm_answer is None:
        return {
            "answer": _citations_only_answer(citations),
            "citations": citations,
            "mode": "citations_only",
        }

    if llm_answer.strip() == "NOT_FOUND":
        # the model judged the retrieved chunks irrelevant; keep the
        # citations visible so the user can verify
        return {
            "answer": NOT_FOUND_ANSWER,
            "citations": citations,
            "mode": "llm",
            "model": llm_service.LLM_MODEL,
        }

    return {
        "answer": llm_answer,
        "citations": citations,
        "mode": "llm",
        "model": llm_service.LLM_MODEL,
    }
