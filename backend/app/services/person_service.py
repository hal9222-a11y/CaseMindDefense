from __future__ import annotations

import difflib
import logging
from collections import Counter

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk, Person, PersonLink
from app.services import llm_service
from app.services.entity_service import CYRILLIC_ENTITY_RE, PHONE_RE, is_noise_name

logger = logging.getLogger(__name__)

# how close a name must be to a phone (in characters) to be a candidate,
# and the distance at which confidence decays to the floor
NEAR_WINDOW = 120
MIN_CONFIDENCE = 0.5

# People get recorded in Hebrew ("יוליה") while the evidence is Russian ("Юля"),
# so a literal name search misses nearly every mention. Match on the Hebrew
# reading of the Cyrillic name, fuzzily — transliteration wobbles (Юлия/Юля both
# give יוליה, but a nickname may come back shorter).
#
# The threshold is deliberately strict. Measured on a real case: the correct
# name scores 1.00, while different people (Алеся, Алина) score 0.60 — so a
# loose bar attributes one person's phone to another, which is far worse in an
# evidence tool than suggesting nothing. Precision over recall here.
CROSS_SCRIPT_MIN_RATIO = 0.85
MAX_CROSS_SCRIPT_LOOKUPS = 15  # each is one LLM round-trip


def _cross_script_names(
    chunks: list[EvidenceChunk], persons: list[Person], aliases: dict[int, list[str]]
) -> dict[int, list[str]]:
    """Cyrillic spellings of the case's people, so a Hebrew-named person can be
    matched against Russian evidence. Only the Cyrillic names that actually sit
    next to a phone number are transliterated — a handful, not the whole corpus.
    Returns {person_id: [cyrillic names]}; empty when no LLM is available."""
    candidates: Counter[str] = Counter()
    for chunk in chunks:
        text = chunk.text or ""
        for m in PHONE_RE.finditer(text):
            window = text[max(0, m.start() - NEAR_WINDOW) : m.end() + NEAR_WINDOW]
            candidates.update(
                tok for tok in CYRILLIC_ENTITY_RE.findall(window) if not is_noise_name(tok)
            )
    if not candidates or not llm_service.ollama_available():
        return {}

    extra: dict[int, list[str]] = {}
    # rank by how often the name sits next to a phone, NOT alphabetically:
    # Cyrillic sorts Ю last, so an alphabetical cut dropped "Юля" — the very
    # name we needed — before it was ever looked up
    for cyrillic, _count in candidates.most_common(MAX_CROSS_SCRIPT_LOOKUPS):
        hebrew = llm_service.to_hebrew_name(cyrillic)
        if not hebrew:
            continue
        for person in persons:
            if any(
                difflib.SequenceMatcher(None, hebrew, known).ratio() >= CROSS_SCRIPT_MIN_RATIO
                for known in _person_names(person, aliases)
            ):
                extra.setdefault(person.id, []).append(cyrillic)
                logger.info("cross-script match: %s ~ %s (%s)", cyrillic, hebrew, person.name)
                break
    return extra


def _existing_phone_links(session: Session, person_ids: list[int]) -> set[tuple[int, str]]:
    if not person_ids:
        return set()
    links = session.exec(
        select(PersonLink).where(
            PersonLink.person_id.in_(person_ids), PersonLink.kind == "phone"
        )
    ).all()
    return {(ln.person_id, _norm_phone(ln.value)) for ln in links}


def _norm_phone(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def _person_names(person: Person, aliases: dict[int, list[str]]) -> list[str]:
    names = [person.name] + aliases.get(person.id, [])
    return [n for n in names if len(n) >= 2]


def _nearest_gap(text: str, name: str, p_start: int, p_end: int) -> int | None:
    """Smallest character gap between the phone span and ANY occurrence of the
    name (text.find returns only the first, which misses a name mentioned
    again right next to the number). None if the name is absent."""
    best: int | None = None
    start = 0
    while True:
        idx = text.find(name, start)
        if idx == -1:
            break
        gap = min(abs(idx - p_end), abs(p_start - (idx + len(name))))
        if best is None or gap < best:
            best = gap
        start = idx + 1
    return best


def suggest_phone_links(session: Session, case_id: int) -> list[dict]:
    """Scan the case's text for phone numbers sitting near a person's name or
    alias and propose linking them. On-demand; nothing is persisted until the
    user accepts. One suggestion per (person, phone), highest confidence kept."""
    persons = session.exec(select(Person).where(Person.case_id == case_id)).all()
    if not persons:
        return []

    person_ids = [p.id for p in persons]
    alias_rows = session.exec(
        select(PersonLink).where(
            PersonLink.person_id.in_(person_ids), PersonLink.kind == "alias"
        )
    ).all()
    aliases: dict[int, list[str]] = {}
    for ln in alias_rows:
        aliases.setdefault(ln.person_id, []).append(ln.value)

    already = _existing_phone_links(session, person_ids)

    case_evidence = {
        e.id: e.filename
        for e in session.exec(select(Evidence).where(Evidence.case_id == case_id)).all()
    }
    chunks = session.exec(
        select(EvidenceChunk).where(EvidenceChunk.evidence_id.in_(list(case_evidence)))
    ).all()

    # a Hebrew-named person is invisible in Russian evidence unless we also look
    # for their Cyrillic spelling
    cross_script = _cross_script_names(chunks, persons, aliases)

    # name occurrences to search for, longest first so "דוד לוי" wins over "דוד"
    name_index: list[tuple[str, Person]] = []
    for p in persons:
        for name in _person_names(p, aliases) + cross_script.get(p.id, []):
            name_index.append((name, p))
    name_index.sort(key=lambda t: -len(t[0]))

    best: dict[tuple[int, str], dict] = {}
    for chunk in chunks:
        text = chunk.text or ""
        for m in PHONE_RE.finditer(text):
            phone = m.group(0)
            norm = _norm_phone(phone)
            p_start, p_end = m.start(), m.end()
            for name, person in name_index:
                if (person.id, norm) in already:
                    continue
                distance = _nearest_gap(text, name, p_start, p_end)
                if distance is None or distance > NEAR_WINDOW:
                    continue
                confidence = round(
                    MIN_CONFIDENCE + (1 - MIN_CONFIDENCE) * (1 - distance / NEAR_WINDOW), 2
                )
                key = (person.id, norm)
                if key not in best or confidence > best[key]["confidence"]:
                    idx = text.find(name)
                    snippet_start = max(0, min(p_start, idx) - 20)
                    snippet_end = min(len(text), max(p_end, idx + len(name)) + 20)
                    best[key] = {
                        "person_id": person.id,
                        "person_name": person.name,
                        "matched_name": name,
                        "phone": phone,
                        "confidence": confidence,
                        "evidence_id": chunk.evidence_id,
                        "filename": case_evidence.get(chunk.evidence_id),
                        "source_location": chunk.source_location,
                        "snippet": text[snippet_start:snippet_end],
                    }

    return sorted(best.values(), key=lambda s: -s["confidence"])


def person_graph(session: Session, case_id: int) -> dict:
    """People of a case as nodes, their explicit relations as labelled edges
    (e.g. A —אח→ B). Lets the user see the who-is-connected-to-who network."""
    persons = session.exec(select(Person).where(Person.case_id == case_id)).all()
    ids = {p.id for p in persons}
    nodes = [
        {"id": p.id, "name": p.name, "description": p.description, "in_evidence": p.in_evidence}
        for p in persons
    ]
    edges = []
    if ids:
        for ln in session.exec(
            select(PersonLink).where(
                PersonLink.person_id.in_(list(ids)), PersonLink.kind == "relation"
            )
        ).all():
            if ln.related_person_id in ids:
                edges.append({"a": ln.person_id, "b": ln.related_person_id, "label": ln.value})
    return {"nodes": nodes, "edges": edges}


NAME_LABELS = {"person", "name", "hebrew_term"}


def _norm_name(name: str) -> str:
    return " ".join(name.split()).strip()


def suggest_alias_links(session: Session, case_id: int) -> list[dict]:
    """Guess that a name appearing in the evidence is a nickname/variant of an
    existing person, so the user can merge them under one person. High
    precision: the candidate must be a name-token of the person's full name
    (e.g. 'דוד' for 'דוד לוי') or a short prefix nickname (דוד -> דודי).
    On-demand; accept by adding an alias link."""
    persons = session.exec(select(Person).where(Person.case_id == case_id)).all()
    if not persons:
        return []
    person_ids = [p.id for p in persons]

    # names already claimed by any person in the case (their own name or an
    # existing alias) — a candidate that IS one of these is not a new alias
    claimed: set[str] = {_norm_name(p.name) for p in persons}
    for ln in session.exec(
        select(PersonLink).where(
            PersonLink.person_id.in_(person_ids), PersonLink.kind == "alias"
        )
    ).all():
        claimed.add(_norm_name(ln.value))

    # candidate names from the case's extracted entities
    from app.models.evidence import ExtractedEntity

    candidates = {
        _norm_name(text)
        for (text, label) in session.exec(
            select(ExtractedEntity.text, ExtractedEntity.label).where(
                ExtractedEntity.evidence_id.in_(
                    select(Evidence.id).where(Evidence.case_id == case_id)
                )
            )
        ).all()
        if label in NAME_LABELS and len(_norm_name(text)) >= 2
    }

    results: list[dict] = []
    for person in persons:
        pname = _norm_name(person.name)
        tokens = set(pname.split())
        for cand in candidates:
            # skip names that are already someone's name or alias (in this
            # case) — a candidate that IS another person is not an alias
            if cand in claimed:
                continue
            confidence = 0.0
            reason = ""
            if cand in tokens:  # 'דוד' is a token of 'דוד לוי'
                confidence, reason = 0.9, "חלק מהשם המלא"
            else:
                for tok in tokens:
                    # short prefix nickname: דוד -> דודי (1-2 extra chars)
                    if len(cand) > len(tok) >= 3 and cand.startswith(tok) and len(cand) - len(tok) <= 2:
                        confidence, reason = 0.6, "כינוי אפשרי"
                        break
            if confidence:
                results.append({
                    "person_id": person.id,
                    "person_name": person.name,
                    "alias": cand,
                    "confidence": confidence,
                    "reason": reason,
                })
    return sorted(results, key=lambda s: -s["confidence"])


def suggest_phone_identities(session: Session, case_id: int) -> list[dict]:
    """Groups of DIFFERENT persons that share the same normalized phone number —
    almost always the same human saved under different names on different phones
    (e.g. "Малой" in the Samsung's contacts, "אמיר גורי" in the iPhone's).
    On-demand suggestions; nothing merges until the user accepts."""
    persons = {
        p.id: p for p in session.exec(select(Person).where(Person.case_id == case_id)).all()
    }
    if not persons:
        return []

    # canonical key = last 9 digits: "972545642339" (international) and
    # "054-564-2339" (local) are the same Israeli number in different dress
    def canonical(value: str) -> str:
        digits = _norm_phone(value)
        return digits[-9:] if len(digits) >= 9 else digits

    by_phone: dict[str, set[int]] = {}
    for link in session.exec(
        select(PersonLink).where(PersonLink.person_id.in_(list(persons)), PersonLink.kind == "phone")
    ).all():
        norm = canonical(link.value)
        if len(norm) >= 6:
            by_phone.setdefault(norm, set()).add(link.person_id)

    suggestions = []
    for phone, ids in by_phone.items():
        if len(ids) < 2:
            continue
        members = [persons[i] for i in sorted(ids)]
        suggestions.append({
            "phone": phone,
            # a shared number is near-certain identity, but family/shared phones
            # exist — leave the final call to the user
            "confidence": 0.9,
            "members": [
                {"person_id": p.id, "name": p.name, "description": p.description}
                for p in members
            ],
        })
    return sorted(suggestions, key=lambda s: s["phone"])


def merge_persons(session: Session, case_id: int, canonical_id: int, merge_ids: list[int]) -> dict:
    """Fold persons into one identity: each merged person's name becomes an
    alias of the canonical, all their links move over (deduped), relations
    pointing at them are re-pointed, and the merged rows are deleted."""
    from app.services.audit_service import log_event

    canonical = session.get(Person, canonical_id)
    if canonical is None or canonical.case_id != case_id:
        raise ValueError("canonical person not found in this case")

    canon_links = session.exec(select(PersonLink).where(PersonLink.person_id == canonical_id)).all()
    seen = {(l.kind, l.value, l.related_person_id) for l in canon_links}
    merged_names = []

    for mid in merge_ids:
        if mid == canonical_id:
            continue
        person = session.get(Person, mid)
        if person is None or person.case_id != case_id:
            raise ValueError(f"person {mid} not found in this case")

        if ("alias", person.name, None) not in seen and person.name != canonical.name:
            session.add(PersonLink(person_id=canonical_id, kind="alias", value=person.name))
            seen.add(("alias", person.name, None))

        for link in session.exec(select(PersonLink).where(PersonLink.person_id == mid)).all():
            key = (link.kind, link.value, link.related_person_id)
            if key in seen:
                session.delete(link)
                continue
            link.person_id = canonical_id
            session.add(link)
            seen.add(key)

        # relations OTHER persons have to the merged one must survive the merge
        for rel in session.exec(select(PersonLink).where(PersonLink.related_person_id == mid)).all():
            rel.related_person_id = canonical_id
            session.add(rel)

        if person.description and person.description not in (canonical.description or ""):
            canonical.description = (canonical.description + " | " if canonical.description else "") + person.description

        merged_names.append(person.name)
        session.delete(person)

    session.add(canonical)
    session.commit()
    log_event(
        session, "persons_merged", case_id=case_id,
        person_id=canonical_id, merged=merged_names,
    )
    return {"person_id": canonical_id, "canonical": canonical.name, "merged": merged_names}
