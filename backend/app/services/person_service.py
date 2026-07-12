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

    # names already claimed (a person's own name or an existing alias) — skip
    claimed: set[str] = {_norm_name(p.name) for p in persons}
    existing_aliases: dict[int, set[str]] = {}
    for ln in session.exec(
        select(PersonLink).where(
            PersonLink.person_id.in_(person_ids), PersonLink.kind == "alias"
        )
    ).all():
        existing_aliases.setdefault(ln.person_id, set()).add(_norm_name(ln.value))
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
        already = existing_aliases.get(person.id, set())
        for cand in candidates:
            if cand == pname or cand in already:
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
