from __future__ import annotations

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

CYRILLIC_RE = re.compile("[Ѐ-ӿ]")
MIN_CYRILLIC_CHARS = 20  # not worth loading a Russian model for a stray word

# Natasha's NER is trained on news text; it reads chat well enough but a span it
# calls a person still has to look like one.
NAME_TAGS = {"Name", "Surn", "Patr"}


@lru_cache(maxsize=1)
def _load():
    """Natasha (Slovnet) NER + pymorphy3 lemmatiser. Both are pure-Python and
    run offline. Returns None if unavailable — callers fall back to regex."""
    try:
        import pymorphy3
        from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter

        embedding = NewsEmbedding()
        return {
            "segmenter": Segmenter(),
            "ner": NewsNERTagger(embedding),
            "morph": pymorphy3.MorphAnalyzer(),
            "Doc": Doc,
        }
    except Exception as exc:  # pragma: no cover - depends on the environment
        logger.warning("Russian NER unavailable, falling back to regex: %s", exc)
        return None


def normalize_name(name: str, morph) -> str:
    """Russian declines names, so Юля / Юлю / Юле are one person written three
    ways — and were three separate entities. Lemmatise to a single form.

    The parse tagged as a personal name is preferred: pymorphy's first parse
    treats 'Насте' as a common noun and yields 'Наст', which re-splits the
    person we are trying to merge.
    """
    words = []
    for word in name.split():
        parses = morph.parse(word)
        if not parses:
            words.append(word)
            continue
        best = next((p for p in parses if NAME_TAGS & set(p.tag.grammemes)), parses[0])
        words.append(best.normal_form.capitalize())
    return " ".join(words)


def extract_russian_entities(text: str) -> list[dict] | None:
    """People, organisations and places in Russian text, with declensions
    merged. Replaces a regex that called every capitalised word a name — which,
    since Russian capitalises the first word of every sentence, meant the top
    three "people" in a real case were Она, Это and Нет.

    Returns [] when the model ran and found nothing — which is an answer, not a
    failure. Only None means "no model", and only then should the caller fall
    back to the regex: falling back on an empty result would put the noise
    straight back in ("Позвони" is an imperative verb, not a person).
    """
    if len(CYRILLIC_RE.findall(text or "")) < MIN_CYRILLIC_CHARS:
        return []

    model = _load()
    if model is None:
        return None

    try:
        doc = model["Doc"](text)
        doc.segment(model["segmenter"])
        doc.tag_ner(model["ner"])
    except Exception as exc:
        logger.warning("Russian NER failed on a chunk: %s", exc)
        return None

    label_of = {"PER": "person", "ORG": "organization", "LOC": "location"}
    entities: list[dict] = []
    for span in doc.spans:
        label = label_of.get(span.type)
        if label is None:
            continue
        text_value = span.text.strip()
        if len(text_value) < 2:
            continue
        if label == "person":
            text_value = normalize_name(text_value, model["morph"])
        entities.append({"text": text_value, "label": label})
    return entities
