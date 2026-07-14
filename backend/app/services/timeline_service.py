from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
import re

from sqlmodel import Session, select

from app.models.evidence import EvidenceChunk

logger = logging.getLogger(__name__)


DATE_RE = re.compile(
    r"\b("
    r"\d{4}-\d{2}-\d{2}"
    r"|"
    r"\d{1,2}/\d{1,2}/\d{2,4}"
    r")\b"
)

SNIPPET_RADIUS = 150  # chars of context on each side of the matched date


def _detect_order(raw_dates: list[str]) -> str:
    """Decide day-first vs month-first ONCE PER DOCUMENT.

    Deciding per date silently mixes conventions inside one file: a WhatsApp
    export containing both 11/21/21 (only valid as month/day) and 11/1/18 had
    the first read as 21 Nov and the second as 11 Jan — a ten-month error in an
    evidence timeline. One slash-date with a component above 12 settles the
    whole document.
    """
    for raw in raw_dates:
        parts = raw.split("/")
        if len(parts) != 3:
            continue
        first, second = int(parts[0]), int(parts[1])
        if first > 12:
            return "day_first"   # 21/11/21 — only day can exceed 12
        if second > 12:
            return "month_first"  # 11/21/21 — only day can exceed 12
    # every date is ambiguous (both parts <= 12); day-first is the local norm
    return "day_first"


def _normalize_date(raw: str, order: str = "day_first") -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None

    try:
        return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass

    formats = (
        ("%d/%m/%Y", "%d/%m/%y") if order == "day_first" else ("%m/%d/%Y", "%m/%d/%y")
    )
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _snippet(text: str, start: int, end: int) -> str:
    left = max(0, start - SNIPPET_RADIUS)
    right = min(len(text), end + SNIPPET_RADIUS)
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def build_timeline(session: Session, case_id: int | None = None) -> list[dict]:
    from app.services.scope import case_evidence_ids

    allowed = case_evidence_ids(session, case_id)

    chunks_by_evidence: dict[int, list[EvidenceChunk]] = defaultdict(list)
    for chunk in session.exec(select(EvidenceChunk)).all():
        if allowed is not None and chunk.evidence_id not in allowed:
            continue
        chunks_by_evidence[chunk.evidence_id].append(chunk)

    events: list[dict] = []
    for evidence_id, chunks in chunks_by_evidence.items():
        raw_dates = [
            m.group(1) for c in chunks for m in DATE_RE.finditer(c.text or "")
        ]
        order = _detect_order(raw_dates)

        # One event per date per passage. A chat line begins with a timestamp, so
        # a passage holds dozens of identical dates — emitting each one buried
        # the timeline in duplicate rows pointing at the same text.
        seen: set[tuple[int, str]] = set()
        for chunk in chunks:
            text = chunk.text or ""
            for match in DATE_RE.finditer(text):
                raw_date = match.group(1)
                normalized = _normalize_date(raw_date, order)
                key = (chunk.chunk_index, normalized or raw_date)
                if key in seen:
                    continue
                seen.add(key)
                events.append(
                    {
                        "date": raw_date,
                        "normalized_date": normalized,
                        "evidence_id": evidence_id,
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
