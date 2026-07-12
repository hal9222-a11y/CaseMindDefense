from __future__ import annotations

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk, Person, PersonLink
from app.services.entity_service import PHONE_RE

# how close a name must be to a phone (in characters) to be a candidate,
# and the distance at which confidence decays to the floor
NEAR_WINDOW = 120
MIN_CONFIDENCE = 0.5


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

    # name occurrences to search for, longest first so "דוד לוי" wins over "דוד"
    name_index: list[tuple[str, Person]] = []
    for p in persons:
        for name in _person_names(p, aliases):
            name_index.append((name, p))
    name_index.sort(key=lambda t: -len(t[0]))

    case_evidence = {
        e.id: e.filename
        for e in session.exec(select(Evidence).where(Evidence.case_id == case_id)).all()
    }
    chunks = session.exec(
        select(EvidenceChunk).where(EvidenceChunk.evidence_id.in_(list(case_evidence)))
    ).all()

    best: dict[tuple[int, str], dict] = {}
    for chunk in chunks:
        text = chunk.text or ""
        for m in PHONE_RE.finditer(text):
            phone = m.group(0)
            norm = _norm_phone(phone)
            p_start, p_end = m.start(), m.end()
            for name, person in name_index:
                idx = text.find(name)
                if idx == -1:
                    continue
                # nearest gap between the name span and the phone span
                distance = min(abs(idx - p_end), abs(p_start - (idx + len(name))))
                if distance > NEAR_WINDOW:
                    continue
                if (person.id, norm) in already:
                    continue
                confidence = round(
                    MIN_CONFIDENCE + (1 - MIN_CONFIDENCE) * (1 - distance / NEAR_WINDOW), 2
                )
                key = (person.id, norm)
                if key not in best or confidence > best[key]["confidence"]:
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
