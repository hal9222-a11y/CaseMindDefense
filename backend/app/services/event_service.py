"""AI event extraction: read the case's conversations and pull out "who did
what, when" as dated events — the things that happened, not just the dates a
regex can already find (that is timeline_service). Each event keeps a citation
so it opens back to the passage it came from.

LLM-backed and bounded: it runs over the passages that actually carry a date
(cheap to find), a batch at a time, and drops anything it cannot ground. No LLM
-> no events (the regex timeline still works); a guessed event is worse than
none in an evidence tool."""
from __future__ import annotations

import json
import logging

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk
from app.services import llm_service
from app.services.timeline_service import DATE_RE

logger = logging.getLogger(__name__)

MAX_PASSAGES = 30           # each is one LLM round-trip; keep the wait bounded
PASSAGE_CHARS = 1200

_SYSTEM = (
    "אתה עוזר ניתוח. לפניך קטע מחומר ראיה. חלץ אירועים ממשיים שקרו — פעולה "
    "שמישהו עשה, פגישה, תשלום, שיחה, מסירה. החזר JSON: מערך של אובייקטים "
    '{"date","actors","action"} בלבד. date בפורמט חופשי כפי שמופיע. actors = '
    "רשימת השמות המעורבים. action = משפט קצר בעברית. אם אין אירוע ברור — החזר []."
)


def extract_events(session: Session, case_id: int) -> list[dict]:
    """LLM-extracted dated events across the case, each with a citation. Empty
    when no LLM is available."""
    if not llm_service.ollama_available():
        return []

    allowed = list(session.exec(
        select(Evidence.id).where(Evidence.case_id == case_id)
    ).all())
    if not allowed:
        return []

    # only passages that carry a date are worth asking about
    dated = [
        c for c in session.exec(
            select(EvidenceChunk).where(EvidenceChunk.evidence_id.in_(allowed))
        ).all()
        if DATE_RE.search(c.text or "")
    ]
    dated.sort(key=lambda c: len(c.text or ""), reverse=True)  # richest first

    events: list[dict] = []
    for chunk in dated[:MAX_PASSAGES]:
        out = llm_service._chat([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (chunk.text or "")[:PASSAGE_CHARS]},
        ])
        for ev in _parse_events(out):
            ev["evidence_id"] = chunk.evidence_id
            ev["chunk_index"] = chunk.chunk_index
            ev["source_location"] = chunk.source_location
            events.append(ev)
    return events


def _parse_events(raw: str | None) -> list[dict]:
    """Pull the JSON array out of the model's reply, defensively — models wrap
    it in prose or fences. Keep only well-formed events."""
    if not raw:
        return []
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return []
    events = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip()
        if not action:
            continue
        actors = item.get("actors")
        if isinstance(actors, str):
            actors = [actors]
        events.append({
            "date": str(item.get("date") or "").strip(),
            "actors": [str(a).strip() for a in (actors or []) if str(a).strip()],
            "action": action[:300],
        })
    return events
