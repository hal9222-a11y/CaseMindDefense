from __future__ import annotations

import re

from sqlmodel import Session, select

from app.models.evidence import EvidenceChunk


LATIN_ENTITY_RE = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")
HEBREW_TOKEN_RE = re.compile(r"[\u0590-\u05FF]{2,}")
PHONE_RE = re.compile(r"\b(?:\+972|0)(?:[-\s]?\d){8,10}\b")
ISRAELI_ID_RE = re.compile(r"\b\d{9}\b")
VEHICLE_PLATE_RE = re.compile(r"\b\d{2,3}[-\s]?\d{2,3}[-\s]?\d{2,3}\b")

HEBREW_STOPWORDS = {
    "אני", "אתה", "את", "הוא", "היא", "אנחנו", "אתם", "אתן", "הם", "הן",
    "של", "על", "עם", "לא", "כן", "זה", "זו", "אלה", "היה", "היו", "יש",
    "אין", "גם", "או", "אם", "כי", "אבל", "אשר", "מתוך", "בין", "עוד", "כל",
}


def _add(counts: dict[str, int], entity: str) -> None:
    entity = (entity or "").strip()

    if not entity:
        return

    counts[entity] = counts.get(entity, 0) + 1


def list_entities(session: Session) -> list[dict]:
    counts: dict[str, int] = {}

    for chunk in session.exec(select(EvidenceChunk)).all():
        text = chunk.text or ""

        for entity in LATIN_ENTITY_RE.findall(text):
            _add(counts, entity)

        for entity in HEBREW_TOKEN_RE.findall(text):
            if entity not in HEBREW_STOPWORDS:
                _add(counts, entity)

        for phone in PHONE_RE.findall(text):
            _add(counts, phone)

        for israeli_id in ISRAELI_ID_RE.findall(text):
            _add(counts, israeli_id)

        for plate in VEHICLE_PLATE_RE.findall(text):
            _add(counts, plate)

    return [
        {"entity": entity, "count": count}
        for entity, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
