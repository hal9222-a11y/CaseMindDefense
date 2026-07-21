from __future__ import annotations

import os

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk
from app.services import llm_service
from app.services.case_analysis_service import role_context
from app.services.scope import case_evidence_ids

# ponytail: bounded so one LLM pass holds the whole context. Raise via env once a
# larger local model is in use; a per-person KNN prefilter is the next step up
# if a case has more than a handful of statement documents.
MAX_SOURCES = int(os.getenv("CASEMIND_CLAIM_MAX_SOURCES", "12"))
SOURCE_CHARS = int(os.getenv("CASEMIND_CLAIM_SOURCE_CHARS", "1500"))

# text-bearing evidence only — a JPG or a ringtone has no claims to compare
_TEXT_STATUSES = ("indexed", "transcribed", "ocr_indexed")
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_SURFACE_TYPES = {"contradiction", "partial", "unclear"}  # skip support/independent


def _as_index(value, count: int) -> int | None:
    """A source index from the model, coerced to a valid int. Local models often
    return it as a string ("0"); None when it isn't a usable index."""
    try:
        idx = int(value)
    except (TypeError, ValueError):
        return None
    return idx if 0 <= idx < count else None


def _source_text(session: Session, evidence_id: int) -> str:
    chunks = session.exec(
        select(EvidenceChunk.text)
        .where(EvidenceChunk.evidence_id == evidence_id)
        .order_by(EvidenceChunk.chunk_index)
    ).all()
    return " ".join(c for c in chunks if c).strip()[:SOURCE_CHARS]


def analyze_claims(
    session: Session,
    case_id: int | None = None,
    evidence_ids: list[int] | None = None,
) -> dict:
    """Claim-level contradiction screening: decompose statements into atomic
    claims, cross-compare within the same person/event/time, classify, and
    verify each flagged pair with a second LLM judge. Returns a table the way a
    defense team reads it — the two claims side by side with type/severity/source.
    """
    allowed = case_evidence_ids(session, case_id)

    if evidence_ids:
        target = [e for e in evidence_ids if allowed is None or e in allowed]
    else:
        query = select(Evidence.id).where(Evidence.status.in_(_TEXT_STATUSES))
        if case_id is not None:
            query = query.where(Evidence.case_id == case_id)
        target = list(session.exec(query.limit(MAX_SOURCES)).all())
    target = target[:MAX_SOURCES]

    sources: list[dict] = []
    for eid in target:
        text = _source_text(session, eid)
        if not text:
            continue
        ev = session.get(Evidence, eid)
        sources.append({"evidence_id": eid, "filename": ev.filename if ev else None, "text": text})

    if len(sources) < 2:
        return {"status": "not_enough_sources", "contradictions": []}
    if not llm_service.ollama_available():
        return {"status": "llm_unavailable", "contradictions": []}

    raw = llm_service.analyze_claim_contradictions(sources, role=role_context(session, case_id))
    if raw is None:
        return {"status": "unparsed", "contradictions": []}

    results: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rel_type = str(item.get("type", "")).lower()
        if rel_type not in _SURFACE_TYPES:
            continue
        claim_a, claim_b = str(item.get("claim_a", "")), str(item.get("claim_b", ""))
        ia = _as_index(item.get("source_a"), len(sources))
        ib = _as_index(item.get("source_b"), len(sources))
        # both claims must map to two DIFFERENT real sources — otherwise it isn't
        # a cross-source contradiction and there's nothing to show side by side
        if not claim_a or not claim_b or ia is None or ib is None or ia == ib:
            continue
        sa, sb = sources[ia], sources[ib]

        # Second-model verification (the user's step 4). A screening hit that the
        # judge calls "consistent" is downgraded, never presented as confirmed.
        verified = None
        if rel_type == "contradiction":
            judged = llm_service.judge_contradiction(claim_a, claim_b)
            verified = judged is not None and judged["verdict"] == "contradiction"

        results.append({
            "claim_a": claim_a,
            "claim_b": claim_b,
            "type": rel_type,
            "severity": str(item.get("severity", "medium")).lower() or "medium",
            "explanation": str(item.get("explanation", "")),
            "verified": verified,  # True/False for contradictions, None for partial/unclear
            "source_a": sa.get("filename"),
            "source_b": sb.get("filename"),
            "evidence_a": sa.get("evidence_id"),
            "evidence_b": sb.get("evidence_id"),
            # navigation aliases: double-click opens evidence A at the claim
            "evidence_id": sa.get("evidence_id"),
            "text": claim_a,
        })

    results.sort(key=lambda r: (_SEVERITY_ORDER.get(r["severity"], 1), r["verified"] is False))
    return {"status": "ok", "contradictions": results}
