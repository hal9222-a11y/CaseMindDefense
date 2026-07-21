"""AI summarization of a single evidence item — the "help me understand this"
tool. A case has hundreds of chats and recordings; nobody reads them all. This
turns one item's chunks into a short Hebrew brief: what it is, who is in it,
what happens, and anything an investigator should not miss.

Grounded, not free-associating: the model sees only this item's own text and is
told to write NOTHING it cannot point to. The summary is a reading aid, never
evidence — the underlying chunks stay the source of truth."""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk, ExtractedEntity
from app.services import llm_service

logger = logging.getLogger(__name__)

# how much of a long item to feed the model — enough for a faithful summary,
# capped so the call stays inside the local model's context and finishes
MAX_SUMMARY_CHARS = 8000

_SYSTEM = (
    "אתה עוזר ניתוח לצוות הגנה פלילי. תקבל קטעים מפריט ראיה אחד. "
    "כתוב סיכום קצר בעברית, אך ורק לפי הקטעים — אל תמציא דבר. מבנה:\n"
    "• סוג החומר ומי מופיע בו\n"
    "• עיקרי הדברים ב-3-5 נקודות\n"
    "• פרטים שחוקר לא צריך לפספס (מספרים, תאריכים, מקומות, סכומים), אם יש\n"
    "אם אין מספיק מידע לסיכום — אמור זאת."
)


def summarize_evidence(session: Session, evidence_id: int) -> dict:
    """A short grounded brief for one evidence item. 503-style None when no LLM.

    Returns {summary, model, people, chunk_count}. people is the item's own
    extracted person entities — cheap, exact, and a useful header even if the
    LLM is unavailable."""
    evidence = session.get(Evidence, evidence_id)
    if evidence is None:
        raise ValueError(f"evidence {evidence_id} not found")

    chunks = session.exec(
        select(EvidenceChunk)
        .where(EvidenceChunk.evidence_id == evidence_id)
        .order_by(EvidenceChunk.chunk_index)
    ).all()
    people = sorted({
        e.text for e in session.exec(
            select(ExtractedEntity).where(
                ExtractedEntity.evidence_id == evidence_id,
                ExtractedEntity.label == "person",
            )
        ).all()
    })

    if not chunks:
        return {
            "summary": None, "model": None, "people": people, "chunk_count": 0,
            "reason": "no_text",
        }
    if not llm_service.ollama_available():
        return {
            "summary": None, "model": None, "people": people,
            "chunk_count": len(chunks), "reason": "no_llm",
        }

    # take from the start and the end so a long conversation's opening AND its
    # latest turns are both represented, not just the first N chars
    joined = _sample_text([c.text or "" for c in chunks], MAX_SUMMARY_CHARS)
    prompt = f"פריט: {evidence.filename}\n\nהקטעים:\n{joined}"
    summary = llm_service._chat([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": prompt},
    ])
    return {
        "summary": summary or None,
        "model": llm_service.active_model(),
        "people": people,
        "chunk_count": len(chunks),
        "reason": None if summary else "llm_failed",
    }


def _sample_text(texts: list[str], budget: int) -> str:
    """Whole text if it fits; otherwise the opening plus the tail, so both ends
    of a long item are seen (the last messages of a chat are often the point)."""
    joined = "\n".join(texts)
    if len(joined) <= budget:
        return joined
    head = joined[: budget * 2 // 3]
    tail = joined[-budget // 3:]
    return f"{head}\n\n[...]\n\n{tail}"
