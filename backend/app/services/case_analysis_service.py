"""Case-level AI understanding: a whole-case overview and investigator
questions, both grounded in a representative sample of the case's own text.

A case here runs to thousands of chunks — far past any local model's context —
so we feed a spread (widely-cited people, flagged passages, a time spread) and
tell the model to write only what the sample supports. These are orientation
aids for a human reading the file, never findings on their own."""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.models.evidence import Case, Evidence, EvidenceChunk, ExtractedEntity
from app.services import llm_service

logger = logging.getLogger(__name__)

SAMPLE_CHARS = 9000
SAMPLE_CHUNKS = 40


def _sample_chunks(session: Session, case_id: int) -> list[EvidenceChunk]:
    """A spread of the case's chunks: prefer flagged (sensitive) passages, then
    fill from across the evidence so one chatty file doesn't dominate."""
    from app.services.flag_service import scan_flags

    allowed_ev = list(session.exec(
        select(Evidence.id).where(Evidence.case_id == case_id)
    ).all())
    if not allowed_ev:
        return []

    chunks = session.exec(
        select(EvidenceChunk).where(EvidenceChunk.evidence_id.in_(allowed_ev))
    ).all()
    by_key = {(c.evidence_id, c.chunk_index): c for c in chunks}

    ordered: list[EvidenceChunk] = []
    seen: set[tuple[int, int]] = set()
    for flag in scan_flags(session, case_id)[:SAMPLE_CHUNKS // 2]:
        key = (flag["evidence_id"], flag["chunk_index"])
        c = by_key.get(key)
        if c and key not in seen:
            ordered.append(c)
            seen.add(key)

    # round-robin the rest across evidence items for breadth
    from collections import defaultdict
    per_ev: dict[int, list[EvidenceChunk]] = defaultdict(list)
    for c in chunks:
        if (c.evidence_id, c.chunk_index) not in seen:
            per_ev[c.evidence_id].append(c)
    lists = list(per_ev.values())
    i = 0
    while len(ordered) < SAMPLE_CHUNKS and any(lists):
        lst = lists[i % len(lists)]
        if lst:
            ordered.append(lst.pop(0))
        i += 1
        lists = [l for l in lists if l]
        if not lists:
            break
    return ordered


def _sample_text(session: Session, case_id: int) -> str:
    parts, total = [], 0
    for c in _sample_chunks(session, case_id):
        t = (c.text or "").strip()
        if not t:
            continue
        parts.append(t)
        total += len(t)
        if total >= SAMPLE_CHARS:
            break
    return "\n---\n".join(parts)


_OVERVIEW_SYSTEM = (
    "אתה עוזר ניתוח לצוות הגנה פלילי. לפניך מדגם מייצג מחומרי תיק. "
    "כתוב סקירה תמציתית בעברית, אך ורק לפי המדגם — אל תמציא:\n"
    "• על מה התיק, בכמה משפטים\n"
    "• הדמויות המרכזיות והקשרים ביניהן\n"
    "• נושאים חוזרים ואירועים בולטים\n"
    "• סימני שאלה / דברים לבדוק לעומק\n"
    "אם המדגם דל מכדי לסכם — אמור זאת."
)

_QUESTIONS_SYSTEM = (
    "אתה חוקר ותיק. לפניך מדגם מחומרי תיק. הצע 5-8 שאלות חקירה חדות "
    "שכדאי לברר, בעברית, כל אחת בשורה נפרדת המתחילה ב-'– '. בסס כל שאלה על "
    "המדגם בלבד. אל תסביר, רק השאלות."
)

_WEAKNESSES_SYSTEM = (
    "אתה יועץ אסטרטגי לסנגוריה פלילית. לפניך מדגם מייצג מחומרי תיק. "
    "נתח את חולשות התיק מנקודת מבט ההגנה, בעברית, אך ורק לפי המדגם — אל תמציא:\n"
    "• סתירות בין גרסאות או בין ראיות\n"
    "• פערים ראייתיים — מה חסר כדי לבסס את טענות התביעה\n"
    "• בעיות מהימנות: תרגום, זיהוי דוברים, הקשר חסר, שרשרת מסירה\n"
    "• פרשנויות חלופיות וקווי הגנה שכדאי לבדוק\n"
    "לכל נקודה ציין על אילו קטעים מהמדגם היא נסמכת. "
    "אם המדגם דל מכדי לנתח — אמור זאת."
)


def role_context(session: Session, case_id: int | None) -> str:
    """The user's declared role in the case ('' when unset)."""
    if not case_id:
        return ""
    case = session.get(Case, case_id)
    return (case.role_context or "").strip() if case else ""


def _analyze(session: Session, case_id: int, system: str, key: str) -> dict:
    """Shared sample->LLM flow for all case-level analyses, with the user's
    role (when set) folded into the system prompt."""
    text = _sample_text(session, case_id)
    if not text:
        return {key: None, "model": None, "reason": "no_text"}
    if not llm_service.ollama_available():
        return {key: None, "model": None, "reason": "no_llm"}
    system = llm_service.with_principles(system)
    role = role_context(session, case_id)
    if role:
        system += f"\nתפקיד המשתמש בתיק: {role}. מקד את הניתוח בשירות התפקיד הזה."
    out = llm_service._chat([
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ])
    return {
        key: out or None,
        "model": llm_service.active_model(),
        "reason": None if out else "llm_failed",
    }


def case_overview(session: Session, case_id: int) -> dict:
    return _analyze(session, case_id, _OVERVIEW_SYSTEM, "overview")


def find_weaknesses(session: Session, case_id: int) -> dict:
    """Defense-lens analysis: contradictions, evidentiary gaps, reliability
    problems and alternative readings — grounded in the sample only."""
    return _analyze(session, case_id, _WEAKNESSES_SYSTEM, "weaknesses")


def suggest_questions(session: Session, case_id: int) -> dict:
    result = _analyze(session, case_id, _QUESTIONS_SYSTEM, "raw")
    out = result.pop("raw")
    questions = []
    for line in (out or "").splitlines():
        line = line.strip().lstrip("–-•*0123456789. ").strip()
        if len(line) > 8:
            questions.append(line)
    return {
        "questions": questions,
        "model": result["model"],
        "reason": result["reason"] or (None if questions else "llm_failed"),
    }
