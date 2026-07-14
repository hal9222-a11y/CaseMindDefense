from __future__ import annotations

import logging
import os
from functools import lru_cache

from app.services.entity_service import (
    CYRILLIC_ENTITY_RE,
    HEBREW_STOPWORDS,
    HEBREW_TOKEN_RE,
    ISRAELI_ID_RE,
    LATIN_ENTITY_RE,
    VEHICLE_PLATE_RE,
    extract_phones,
    is_noise_name,
    looks_like_a_date,
    mask_phones,
    valid_israeli_id,
)
from app.services.russian_ner import extract_russian_entities

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
                # Only the categories we actually mean. Falling back to the raw
                # model code leaked its internal tags to the user as entity
                # types — "duc", "ang", "misc" — carrying values like "ip",
                # "mn" and ". 2". Noise dressed up as findings.
                label = LABEL_MAP.get(group)
                if label is None:
                    continue
                entities.append({"text": word, "label": label})
        except Exception as exc:
            logger.warning("NER inference failed on chunk: %s", exc)

    # Russian: a real NER model, not "every capitalised word is a name". The
    # regex is a fallback for a missing model ONLY — an empty result from the
    # model is an answer, and falling back on it would put the noise back.
    russian = extract_russian_entities(text)
    if russian is None:
        for entity in CYRILLIC_ENTITY_RE.findall(text):
            if not is_noise_name(entity):
                entities.append({"text": entity, "label": "name"})
    else:
        entities.extend(russian)

    # Phones via libphonenumber: it validates the number and understands other
    # countries. The old pattern was Israel-only, so the Russian (+7) and
    # Belarusian (+375) numbers in this material were invisible.
    for phone in extract_phones(text):
        entities.append({"text": phone, "label": "phone"})

    # The ID and plate patterns are just runs of digits, so they happily match
    # *inside* a phone number ("052-465-7474" also yielded the "plate" 465-7474)
    # and inside dates in filenames. Blank out what is already a phone first.
    remaining = mask_phones(text)
    for israeli_id in ISRAELI_ID_RE.findall(remaining):
        # verify the check digit: half the "IDs" found in the real case were junk
        if valid_israeli_id(israeli_id):
            entities.append({"text": israeli_id, "label": "israeli_id"})
    for plate in VEHICLE_PLATE_RE.findall(remaining):
        # every "plate" in the real case was a date out of a WhatsApp filename
        if not looks_like_a_date(plate):
            entities.append({"text": plate, "label": "vehicle_plate"})

    if ner is None:
        for entity in LATIN_ENTITY_RE.findall(text):
            entities.append({"text": entity, "label": "name"})
        for entity in HEBREW_TOKEN_RE.findall(text):
            if entity not in HEBREW_STOPWORDS:
                entities.append({"text": entity, "label": "hebrew_term"})

    return entities
