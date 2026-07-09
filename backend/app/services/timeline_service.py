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


def build_timeline(session: Session) -> list[dict]:
    events: list[dict] = []

    for chunk in session.exec(select(EvidenceChunk)).all():
        for raw_date in DATE_RE.findall(chunk.text or ""):
            normalized = _normalize_date(raw_date)

            events.append(
                {
                    "date": raw_date,
                    "normalized_date": normalized,
                    "evidence_id": chunk.evidence_id,
                    "chunk_index": chunk.chunk_index,
                    "source_location": chunk.source_location,
                    "text": chunk.text,
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
