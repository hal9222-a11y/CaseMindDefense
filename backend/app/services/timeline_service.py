from __future__ import annotations

from datetime import datetime
import re

from sqlmodel import Session, select

from app.models.evidence import EvidenceChunk


DATE_RE = re.compile(
    r"\b("
    r"\d{4}-\d{2}-\d{2}"
    r"|"
    r"\d{1,2}/\d{1,2}/\d{2,4}"
    r")\b"
)


def _normalize_date(raw: str) -> str | None:
    raw = (raw or "").strip()

    if not raw:
        return None

    try:
        return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass

    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue

    return None


SNIPPET_RADIUS = 150  # chars of context on each side of the matched date


def _snippet(text: str, start: int, end: int) -> str:
    left = max(0, start - SNIPPET_RADIUS)
    right = min(len(text), end + SNIPPET_RADIUS)
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def build_timeline(session: Session, case_id: int | None = None) -> list[dict]:
    from app.services.scope import case_evidence_ids

    allowed = case_evidence_ids(session, case_id)
    events: list[dict] = []

    for chunk in session.exec(select(EvidenceChunk)).all():
        if allowed is not None and chunk.evidence_id not in allowed:
            continue
        text = chunk.text or ""
        for match in DATE_RE.finditer(text):
            raw_date = match.group(1)

            events.append(
                {
                    "date": raw_date,
                    "normalized_date": _normalize_date(raw_date),
                    "evidence_id": chunk.evidence_id,
                    "chunk_index": chunk.chunk_index,
                    "source_location": chunk.source_location,
                    "text": _snippet(text, match.start(), match.end()),
                }
            )

    events.sort(
        key=lambda item: (
            item.get("normalized_date") is None,
            item.get("normalized_date") or item.get("date") or "",
            item.get("evidence_id") or 0,
            item.get("chunk_index") or 0,
        )
    )

    return events
