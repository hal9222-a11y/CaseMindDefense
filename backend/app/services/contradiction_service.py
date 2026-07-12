from __future__ import annotations

import os

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk
from app.services import llm_service
from app.services.embedding_service import (
    cosine_similarity,
    deserialize_embedding,
    embedding_model_name,
)

SIM_THRESHOLD = float(os.getenv("CASEMIND_CONTRADICTION_SIM_THRESHOLD", "0.72"))
MAX_CHUNKS = int(os.getenv("CASEMIND_CONTRADICTION_MAX_CHUNKS", "500"))
MAX_LLM_PAIRS = int(os.getenv("CASEMIND_CONTRADICTION_MAX_PAIRS", "8"))

SNIPPET_CHARS = 300


def find_contradictions(
    session: Session,
    sim_threshold: float | None = None,
    max_llm_pairs: int | None = None,
    case_id: int | None = None,
) -> list[dict]:
    """Semantically similar chunk pairs from different evidence, judged by
    the local LLM. Without an LLM, top pairs are returned as 'unverified'."""
    from app.services.scope import case_evidence_ids

    threshold = SIM_THRESHOLD if sim_threshold is None else sim_threshold
    pairs_cap = MAX_LLM_PAIRS if max_llm_pairs is None else max_llm_pairs

    allowed = case_evidence_ids(session, case_id)
    current_model = embedding_model_name()
    chunks = session.exec(select(EvidenceChunk).limit(MAX_CHUNKS)).all()

    embedded: list[tuple[EvidenceChunk, list[float]]] = []
    for chunk in chunks:
        if allowed is not None and chunk.evidence_id not in allowed:
            continue
        if chunk.embedding_model and chunk.embedding_model != current_model:
            continue
        vec = deserialize_embedding(chunk.embedding or "")
        if vec:
            embedded.append((chunk, vec))

    # ponytail: O(n^2) pairing capped at MAX_CHUNKS chunks; switch the
    # candidate step to sqlite-vec KNN when real corpora get large
    candidates: list[tuple[float, EvidenceChunk, EvidenceChunk]] = []
    for i in range(len(embedded)):
        chunk_a, vec_a = embedded[i]
        for j in range(i + 1, len(embedded)):
            chunk_b, vec_b = embedded[j]
            if chunk_a.evidence_id == chunk_b.evidence_id:
                continue
            similarity = cosine_similarity(vec_a, vec_b)
            if similarity >= threshold:
                candidates.append((similarity, chunk_a, chunk_b))

    candidates.sort(key=lambda item: -item[0])

    use_llm = llm_service.ollama_available()
    evidence_cache: dict[int, Evidence | None] = {}

    def _filename(evidence_id: int) -> str | None:
        if evidence_id not in evidence_cache:
            evidence_cache[evidence_id] = session.get(Evidence, evidence_id)
        ev = evidence_cache[evidence_id]
        return ev.filename if ev else None

    results: list[dict] = []
    for similarity, chunk_a, chunk_b in candidates[:pairs_cap]:
        verdict, explanation = "unverified", ""
        if use_llm:
            judged = llm_service.judge_contradiction(chunk_a.text, chunk_b.text)
            if judged is not None:
                if judged["verdict"] == "consistent":
                    continue
                verdict, explanation = "contradiction", judged["explanation"]

        results.append(
            {
                "verdict": verdict,
                "similarity": round(float(similarity), 4),
                "explanation": explanation,
                "filename_a": _filename(chunk_a.evidence_id),
                "filename_b": _filename(chunk_b.evidence_id),
                "evidence_a": chunk_a.evidence_id,
                "evidence_b": chunk_b.evidence_id,
                "text_a": (chunk_a.text or "")[:SNIPPET_CHARS],
                "text_b": (chunk_b.text or "")[:SNIPPET_CHARS],
                # navigation aliases: double-click opens evidence A at the chunk
                "evidence_id": chunk_a.evidence_id,
                "text": (chunk_a.text or "")[:SNIPPET_CHARS],
            }
        )
    return results
