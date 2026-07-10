from __future__ import annotations

import logging
import os
from functools import lru_cache

from app.services.entity_service import (
    HEBREW_STOPWORDS,
    HEBREW_TOKEN_RE,
    ISRAELI_ID_RE,
    LATIN_ENTITY_RE,
    PHONE_RE,
    VEHICLE_PLATE_RE,
)

logger = logging.getLogger(__name__)

NER_MODEL_NAME = os.getenv("CASEMIND_NER_MODEL", "dicta-il/dictabert-ner")
NER_MIN_SCORE = float(os.getenv("CASEMIND_NER_MIN_SCORE", "0.5"))

LABEL_MAP = {
    "PER": "person",
    "ORG": "organization",
    "LOC": "location",
    "GPE": "location",
    "FAC": "location",
    "TIMEX": "time",
    "TTL": "title",
}


@lru_cache(maxsize=1)
def _load_ner():
    try:
        from transformers import pipeline

        return pipeline(
            "token-classification",
            model=NER_MODEL_NAME,
            aggregation_strategy="simple",
        )
    except Exception as exc:
        logger.warning("NER model unavailable, using regex fallback: %s", exc)
        return None


def extract_entities(text: str) -> list[dict]:
    """Returns [{'text': ..., 'label': ...}] for one chunk of text.

    Model entities (Hebrew NER) when available; deterministic patterns
    (phones, IDs, plates) always; regex token fallback when no model."""
    text = (text or "").strip()
    if not text:
        return []

    entities: list[dict] = []
    ner = _load_ner()

    if ner is not None:
        try:
            for ent in ner(text):
                word = (ent.get("word") or "").strip()
                if len(word) < 2 or float(ent.get("score", 0.0)) < NER_MIN_SCORE:
                    continue
                group = ent.get("entity_group") or ""
                label = LABEL_MAP.get(group, group.lower() or "other")
                entities.append({"text": word, "label": label})
        except Exception as exc:
            logger.warning("NER inference failed on chunk: %s", exc)

    for phone in PHONE_RE.findall(text):
        entities.append({"text": phone.strip(), "label": "phone"})
    for israeli_id in ISRAELI_ID_RE.findall(text):
        entities.append({"text": israeli_id, "label": "israeli_id"})
    for plate in VEHICLE_PLATE_RE.findall(text):
        entities.append({"text": plate, "label": "vehicle_plate"})

    if ner is None:
        for entity in LATIN_ENTITY_RE.findall(text):
            entities.append({"text": entity, "label": "name"})
        for entity in HEBREW_TOKEN_RE.findall(text):
            if entity not in HEBREW_STOPWORDS:
                entities.append({"text": entity, "label": "hebrew_term"})

    return entities
