from __future__ import annotations

import os
import re

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk


LATIN_ENTITY_RE = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")
CYRILLIC_ENTITY_RE = re.compile(r"\b[А-ЯЁ][а-яё]{2,}\b")
HEBREW_TOKEN_RE = re.compile(r"[\u0590-\u05FF]{2,}")
# (?<!\d) instead of \b: there is no word boundary between a space and "+",
# so \b(?:\+972...) can never match international numbers
# Kept for the fallback path and for locating a number's position in the text.
PHONE_RE = re.compile(r"(?<!\d)(?:\+972|0)(?:[-\s]?\d){8,10}\b")

DEFAULT_PHONE_REGION = os.getenv("CASEMIND_PHONE_REGION", "IL")


def extract_phones(text: str) -> list[str]:
    """Phone numbers via libphonenumber: validated, and not Israel-only.

    The regex above only matches Israeli numbers, so the Russian (+7),
    Belarusian (+375) and Spanish (+34) numbers in this case were never seen at
    all — and it happily accepted any 9-11 digit run beginning with 0, which is
    also what a date or an ID looks like. Numbers are returned in E.164 so the
    same phone written three ways is one phone.
    """
    try:
        import phonenumbers
    except ImportError:  # pragma: no cover - fallback when the lib is absent
        return [p.strip() for p in PHONE_RE.findall(text or "")]

    found: list[str] = []
    seen: set[str] = set()
    for match in phonenumbers.PhoneNumberMatcher(text or "", DEFAULT_PHONE_REGION):
        e164 = phonenumbers.format_number(
            match.number, phonenumbers.PhoneNumberFormat.E164
        )
        if e164 not in seen:
            seen.add(e164)
            found.append(e164)
    return found


def mask_phones(text: str) -> str:
    """Blank out phone numbers so the ID and plate patterns — which are just runs
    of digits — cannot match a fragment of one. '052-465-7474' was also being
    reported as the vehicle plate '465-7474'."""
    try:
        import phonenumbers
    except ImportError:  # pragma: no cover
        return PHONE_RE.sub(lambda m: " " * len(m.group(0)), text or "")

    masked = list(text or "")
    for match in phonenumbers.PhoneNumberMatcher(text or "", DEFAULT_PHONE_REGION):
        for i in range(match.start, match.end):
            masked[i] = " "
    return "".join(masked)
ISRAELI_ID_RE = re.compile(r"\b\d{9}\b")
VEHICLE_PLATE_RE = re.compile(r"\b\d{2,3}[-\s]?\d{2,3}[-\s]?\d{2,3}\b")

HEBREW_STOPWORDS = {
    "אני", "אתה", "את", "הוא", "היא", "אנחנו", "אתם", "אתן", "הם", "הן",
    "של", "על", "עם", "לא", "כן", "זה", "זו", "אלה", "היה", "היו", "יש",
    "אין", "גם", "או", "אם", "כי", "אבל", "אשר", "מתוך", "בין", "עוד", "כל",
}

# Russian capitalises the first word of every sentence, so CYRILLIC_ENTITY_RE
# tags pronouns and particles as names (Она/Это/Нет were the top 3 "names" in a
# real chat). Same job HEBREW_STOPWORDS does for Hebrew.
RUSSIAN_STOPWORDS = {
    "я", "ты", "он", "она", "оно", "мы", "вы", "они",
    "мне", "меня", "тебе", "тебя", "ему", "ей", "им", "нам", "нас", "вам", "вас",
    "мой", "моя", "твой", "твоя", "свой", "себя",
    "это", "этот", "эта", "эти", "тот", "та", "те", "там", "тут", "здесь",
    "да", "нет", "не", "ни", "и", "а", "но", "или", "если", "что", "чтобы",
    "как", "так", "такой", "какой", "кто", "где", "когда", "почему", "зачем",
    "все", "всё", "весь", "вся", "уже", "ещё", "еще", "тоже", "только", "просто",
    "очень", "может", "можно", "надо", "нужно", "хорошо", "ладно", "конечно",
    "спасибо", "привет", "пока", "вот", "ну", "ага", "ок", "оки", "давай",
    "был", "была", "было", "были", "есть", "будет", "буду", "потом", "сейчас",
    "сегодня", "завтра", "вчера", "утром", "вечером", "почти", "тогда", "теперь",
    "отлично", "хочу", "знаю", "думаю", "говорит", "сказал", "сказала",
    # chat fillers and imperatives that open a sentence in a WhatsApp thread
    "потому", "поэтому", "скажи", "скажите", "слушай", "слушайте", "смотри",
    "короче", "блин", "значит", "кстати", "вообще", "наверное", "кажется",
    "понятно", "точно", "честно", "нормально", "спокойно", "интересно",
    "странно", "жаль", "боже", "господи", "правда", "конец", "начало",
    "пусть", "ясно", "ппц", "посмотри", "помнишь", "представляешь", "хватит",
}


def is_noise_name(text: str) -> bool:
    """A capitalised Cyrillic token that is really a pronoun/particle/filler,
    not a person. Shared by extraction (don't store it) and listing (don't show
    the ones already stored, so existing cases are cleaned without a reindex)."""
    word = (text or "").strip()
    if word.lower() in RUSSIAN_STOPWORDS:
        return True
    # interjections like "Ааа"/"Ооо" — a single letter repeated is never a name
    return len(set(word.lower())) == 1 and len(word) > 1


def _add(counts: dict[tuple[str, str], int], entity: str, entity_type: str) -> None:
    entity = (entity or "").strip()

    if not entity:
        return

    key = (entity, entity_type)
    counts[key] = counts.get(key, 0) + 1


def list_entities(session: Session, case_id: int | None = None) -> list[dict]:
    """Aggregates entities extracted at index time (see ner_service).
    Falls back to a legacy regex scan of chunks for evidence indexed
    before entity extraction existed."""
    from sqlalchemy import func

    from app.models.evidence import ExtractedEntity

    stmt = select(ExtractedEntity.text, ExtractedEntity.label, func.count())
    if case_id is not None:
        stmt = stmt.where(
            ExtractedEntity.evidence_id.in_(
                select(Evidence.id).where(Evidence.case_id == case_id)
            )
        )
    rows = session.exec(stmt.group_by(ExtractedEntity.text, ExtractedEntity.label)).all()

    if rows:
        # filter on read too: evidence indexed before the stopword list existed
        # still has the noise stored, and re-OCRing every file to purge it is
        # not worth it
        return [
            {"entity": text, "type": label, "count": count}
            for text, label, count in sorted(rows, key=lambda r: (-r[2], r[0]))
            if not is_noise_name(text)
        ]

    return _legacy_regex_scan(session) if case_id is None else []


# Deterministic pattern matches, not things you reason about in a network.
# Filtering these out (rather than whitelisting names) keeps locations and
# organizations, which very much belong in an investigation graph.
IDENTIFIER_LABELS = {"phone", "israeli_id", "vehicle_plate"}


def entity_graph(
    session: Session,
    max_nodes: int = 30,
    max_edges: int = 200,
    case_id: int | None = None,
    exclude_types: set[str] | None = None,
    min_count: int = 1,
    min_edge_weight: int = 1,
    max_edges_per_node: int = 3,
) -> dict:
    """Co-occurrence graph: nodes are the top entities, an edge connects two
    entities mentioned in the same PASSAGE (weight = how many passages).

    Co-occurrence per file is worthless here: one WhatsApp export contains every
    participant, so every pair "co-occurs" and the graph is a complete hairball
    that says nothing. Sharing a passage means they were actually talked about
    together."""
    from collections import Counter, defaultdict
    from itertools import combinations

    from app.models.evidence import ExtractedEntity

    stmt = select(
        ExtractedEntity.text,
        ExtractedEntity.label,
        ExtractedEntity.evidence_id,
        ExtractedEntity.chunk_index,
    )
    if case_id is not None:
        stmt = stmt.where(
            ExtractedEntity.evidence_id.in_(
                select(Evidence.id).where(Evidence.case_id == case_id)
            )
        )
    rows = [
        row for row in session.exec(stmt).all()
        # same noise filter the Entities list uses — the graph was showing
        # Она/Это/Нет as if they were people
        if not is_noise_name(row[0]) and (exclude_types is None or row[1] not in exclude_types)
    ]

    counts: Counter = Counter((text, label) for text, label, _, _ in rows)
    top = {
        key for key, count in counts.most_common(max_nodes) if count >= min_count
    }

    # keyed by passage, not by file — see the docstring
    entities_by_passage: dict[tuple[int, int], set] = defaultdict(set)
    for text, label, evidence_id, chunk_index in rows:
        if (text, label) in top:
            entities_by_passage[(evidence_id, chunk_index)].add((text, label))

    edge_weights: Counter = Counter()
    for entities in entities_by_passage.values():
        for a, b in combinations(sorted(entities), 2):
            edge_weights[(a, b)] += 1

    nodes = [
        {"entity": text, "type": label, "count": counts[(text, label)]}
        for text, label in sorted(top, key=lambda key: -counts[key])
    ]
    # Keep only each entity's strongest links. A threshold alone cannot fix this:
    # passages are long enough that most names still co-occur with most others
    # (94% density), and a near-complete graph shows nothing however it is drawn.
    # Top-k per node keeps the picture readable and, more importantly, keeps the
    # link that actually matters for each person.
    strongest: dict[tuple, list] = defaultdict(list)
    for pair, weight in edge_weights.most_common():
        if weight < min_edge_weight:
            continue
        a, b = pair
        strongest[a].append((weight, pair))
        strongest[b].append((weight, pair))

    kept: set = set()
    for node, node_edges in strongest.items():
        for _weight, pair in sorted(node_edges, reverse=True)[:max_edges_per_node]:
            kept.add(pair)

    edges = [
        {"a": a[0], "b": b[0], "weight": edge_weights[(a, b)]}
        for (a, b) in sorted(kept, key=lambda p: -edge_weights[p])[:max_edges]
    ]
    return {"nodes": nodes, "edges": edges}


def _legacy_regex_scan(session: Session) -> list[dict]:
    counts: dict[tuple[str, str], int] = {}

    for chunk in session.exec(select(EvidenceChunk)).all():
        text = chunk.text or ""

        for entity in LATIN_ENTITY_RE.findall(text):
            _add(counts, entity, "name")

        for entity in HEBREW_TOKEN_RE.findall(text):
            if entity not in HEBREW_STOPWORDS:
                _add(counts, entity, "hebrew_term")

        for phone in PHONE_RE.findall(text):
            _add(counts, phone, "phone")

        for israeli_id in ISRAELI_ID_RE.findall(text):
            _add(counts, israeli_id, "israeli_id")

        for plate in VEHICLE_PLATE_RE.findall(text):
            _add(counts, plate, "vehicle_plate")

    return [
        {"entity": entity, "type": entity_type, "count": count}
        for (entity, entity_type), count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
