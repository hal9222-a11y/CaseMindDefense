from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_session
from app.models.evidence import Case, Evidence, Person, PersonLink
from app.services import llm_service
from app.services.audit_service import log_event
from app.services.person_service import merge_persons, person_graph, suggest_alias_links, suggest_phone_identities, suggest_phone_links

router = APIRouter(prefix="/persons", tags=["persons"])

LINK_KINDS = {"alias", "phone", "photo", "relation"}

_CYRILLIC_RE = re.compile("[Ѐ-ӿ]")
_HEBREW_RE = re.compile("[֐-׿]")


def _hebrew_reading(name: str, links: list[PersonLink]) -> str | None:
    """The stored Hebrew reading of a Cyrillic name (an alias in Hebrew),
    for showing beside the original. None for non-Cyrillic names."""
    if not _CYRILLIC_RE.search(name or ""):
        return None
    for ln in links:
        if ln.kind == "alias" and _HEBREW_RE.search(ln.value or ""):
            return ln.value
    return None


class CreatePersonRequest(BaseModel):
    case_id: int
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    in_evidence: bool = True


class UpdatePersonRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None


class AddLinkRequest(BaseModel):
    kind: str
    value: str = ""
    evidence_id: int | None = None
    related_person_id: int | None = None


def _person_dict(session: Session, person: Person) -> dict:
    links = session.exec(
        select(PersonLink).where(PersonLink.person_id == person.id).order_by(PersonLink.id)
    ).all()
    return {
        "id": person.id,
        "case_id": person.case_id,
        "name": person.name,
        "name_he": _hebrew_reading(person.name, links),
        "description": person.description,
        "in_evidence": person.in_evidence,
        "links": [
            {
                "id": ln.id,
                "kind": ln.kind,
                "value": ln.value,
                "evidence_id": ln.evidence_id,
                "related_person_id": ln.related_person_id,
                "confidence": ln.confidence,
            }
            for ln in links
        ],
    }


@router.get("/suggest-phone-links")
def suggest_phones(case_id: int = Query(...), session: Session = Depends(get_session)):
    """The system's guess of which phone numbers belong to which people,
    based on how close the number sits to a person's name/alias in the
    text. Nothing is saved — accept a suggestion via POST /links."""
    return suggest_phone_links(session, case_id)


@router.get("/suggest-aliases")
def suggest_aliases(case_id: int = Query(...), session: Session = Depends(get_session)):
    """Guess that a name in the evidence is a nickname/variant of an existing
    person (part of the full name, or a short prefix nickname)."""
    return suggest_alias_links(session, case_id)


@router.post("/translate-names")
def translate_names(case_id: int = Query(...), session: Session = Depends(get_session)):
    """For each person in the case whose name is in Cyrillic and has no Hebrew
    reading yet, transliterate it to Hebrew (local LLM) and store it as an
    alias, so the Russian name can be shown with its Hebrew form. Returns the
    names that were added."""
    if not llm_service.ollama_available():
        raise HTTPException(
            status_code=503,
            detail="תרגום שמות דורש מודל שפה מקומי (Ollama) — לא זמין כרגע",
        )
    persons = session.exec(select(Person).where(Person.case_id == case_id)).all()
    added: list[dict] = []
    for person in persons:
        if not _CYRILLIC_RE.search(person.name):
            continue
        links = session.exec(
            select(PersonLink).where(PersonLink.person_id == person.id)
        ).all()
        if _hebrew_reading(person.name, links) is not None:
            continue  # already has a Hebrew reading
        hebrew = llm_service.to_hebrew_name(person.name)
        if not hebrew or not _HEBREW_RE.search(hebrew):
            continue  # model unavailable or gave nothing usable
        session.add(PersonLink(person_id=person.id, kind="alias", value=hebrew))
        session.commit()
        log_event(session, "person_name_translated", case_id=case_id,
                  name=person.name, value=hebrew)
        added.append({"id": person.id, "name": person.name, "name_he": hebrew})
    return {"translated": added, "count": len(added)}


@router.get("/suggest-phone-identities")
def suggest_phone_identities_endpoint(case_id: int = Query(...), session: Session = Depends(get_session)):
    """Different persons sharing one phone number across the case's sources —
    the 'saved as X on one phone, Y on the other' unification."""
    return suggest_phone_identities(session, case_id)


class MergePersonsRequest(BaseModel):
    case_id: int
    canonical_id: int
    merge_ids: list[int]


@router.post("/merge")
def merge_persons_endpoint(req: MergePersonsRequest, session: Session = Depends(get_session)):
    try:
        return merge_persons(session, req.case_id, req.canonical_id, req.merge_ids)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/graph")
def graph(case_id: int = Query(...), session: Session = Depends(get_session)):
    """People as nodes and their relations as labelled edges (who-vs-who)."""
    return person_graph(session, case_id)


@router.get("/suggest-identities")
def suggest_identities_endpoint(case_id: int = Query(...), session: Session = Depends(get_session)):
    """Entity resolution suggestions: clusters of written names (רינה / Рина /
    Rina / Риночка) that are likely the same human — cross-script
    transliteration, Russian diminutives, fuzzy spelling. Offline and
    deterministic; nothing merges until accepted."""
    from app.services.resolution_service import suggest_identities

    return suggest_identities(session, case_id)


class ResolveIdentityRequest(BaseModel):
    case_id: int
    canonical: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)


@router.post("/resolve")
def resolve_identity(req: ResolveIdentityRequest, session: Session = Depends(get_session)):
    """Accept one identity cluster: find-or-create the person and attach the
    other written forms as alias links (visible, deletable, audited)."""
    from app.services.resolution_service import apply_identity

    return apply_identity(session, req.case_id, req.canonical, req.aliases)


@router.post("/auto-resolve")
def auto_resolve_endpoint(case_id: int = Query(...), session: Session = Depends(get_session)):
    """Apply every high-confidence identity cluster automatically; lower ones
    stay in /suggest-identities for the user to judge."""
    from app.services.resolution_service import auto_resolve

    return auto_resolve(session, case_id)


@router.get("/connections")
def connections_endpoint(
    seed: str = Query(..., min_length=2),
    case_id: int = Query(...),
    session: Session = Depends(get_session),
):
    """Ask for a person or a number and get what it is connected to: the names it
    is saved under, the people and (named) phones that co-occur with it in the
    evidence — most-connected first — and the passages it appears in. A phone
    seed follows the number through all its aliases."""
    from app.services.connections_service import find_connections

    return find_connections(session, case_id, seed)


@router.get("/phone-directory")
def phone_directory_endpoint(case_id: int = Query(...), session: Session = Depends(get_session)):
    """Every phone number in the case -> the name(s) it is saved under, folded
    across spelling/nickname variants and across each device's phonebook. Numbers
    saved under several different identities (the 'X here, Y there' signal) sort
    first. Read-only — derived from the extracted contacts, nothing is written."""
    from app.services.phonebook_service import phone_directory

    return phone_directory(session, case_id)


@router.get("/phone-lookup")
def phone_lookup_endpoint(
    number: str = Query(..., min_length=4),
    case_id: int = Query(...),
    session: Session = Depends(get_session),
):
    """One number -> the name(s) it is saved under across the case, with its
    spelling/nickname variants grouped. Formatting is ignored (052-222-8282 ==
    0542228282)."""
    from app.services.phonebook_service import lookup_phone

    return lookup_phone(session, case_id, number)


@router.get("/knowledge-graph")
def knowledge_graph_endpoint(case_id: int = Query(...), session: Session = Depends(get_session)):
    """The case as one network: resolved people (all their written forms folded
    into one node), phones, locations, organizations and vehicles — with typed,
    evidence-cited edges."""
    from app.services.knowledge_service import knowledge_graph

    return knowledge_graph(session, case_id)


@router.get("/suggest-relations")
def suggest_relations_endpoint(case_id: int = Query(...), session: Session = Depends(get_session)):
    """LLM-read relation suggestions for strongly co-mentioned people who have
    no labeled relation yet. Suggestions carry the passages they were read
    from; accept one via POST /{person_id}/links (kind=relation)."""
    from app.services.inference_service import suggest_relations

    return suggest_relations(session, case_id)


@router.get("")
def list_persons(case_id: int = Query(...), session: Session = Depends(get_session)):
    persons = session.exec(
        select(Person).where(Person.case_id == case_id).order_by(Person.name)
    ).all()
    return [_person_dict(session, p) for p in persons]


@router.post("")
def create_person(req: CreatePersonRequest, session: Session = Depends(get_session)):
    if not session.get(Case, req.case_id):
        raise HTTPException(status_code=404, detail="case not found")
    person = Person(
        case_id=req.case_id,
        name=req.name.strip(),
        description=req.description.strip(),
        in_evidence=req.in_evidence,
    )
    session.add(person)
    session.commit()
    session.refresh(person)
    log_event(session, "person_created", case_id=req.case_id, name=person.name)
    return _person_dict(session, person)


@router.patch("/{person_id}")
def update_person(person_id: int, req: UpdatePersonRequest, session: Session = Depends(get_session)):
    person = session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="person not found")
    if req.name is not None and req.name.strip():
        person.name = req.name.strip()
    if req.description is not None:
        person.description = req.description.strip()
    session.add(person)
    session.commit()
    session.refresh(person)
    return _person_dict(session, person)


@router.delete("/{person_id}")
def delete_person(person_id: int, session: Session = Depends(get_session)):
    person = session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="person not found")
    # drop this person's links and any relation links pointing at them
    for link in session.exec(
        select(PersonLink).where(
            (PersonLink.person_id == person_id)
            | (PersonLink.related_person_id == person_id)
        )
    ).all():
        session.delete(link)
    session.delete(person)
    session.commit()
    log_event(session, "person_deleted", case_id=person.case_id, name=person.name)
    return {"deleted": person_id}


@router.post("/{person_id}/links")
def add_link(person_id: int, req: AddLinkRequest, session: Session = Depends(get_session)):
    person = session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="person not found")
    if req.kind not in LINK_KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {sorted(LINK_KINDS)}")
    if req.kind == "photo":
        if req.evidence_id is None or not session.get(Evidence, req.evidence_id):
            raise HTTPException(status_code=422, detail="photo link needs a valid evidence_id")
    if req.kind == "relation":
        if req.related_person_id is None or not session.get(Person, req.related_person_id):
            raise HTTPException(status_code=422, detail="relation link needs a valid related_person_id")

    link = PersonLink(
        person_id=person_id,
        kind=req.kind,
        value=req.value.strip(),
        evidence_id=req.evidence_id,
        related_person_id=req.related_person_id,
    )
    session.add(link)
    session.commit()
    session.refresh(link)
    log_event(session, "person_link_added", case_id=person.case_id, name=person.name, kind=req.kind)
    return _person_dict(session, person)


@router.delete("/{person_id}/links/{link_id}")
def remove_link(person_id: int, link_id: int, session: Session = Depends(get_session)):
    link = session.get(PersonLink, link_id)
    if not link or link.person_id != person_id:
        raise HTTPException(status_code=404, detail="link not found")
    session.delete(link)
    session.commit()
    person = session.get(Person, person_id)
    return _person_dict(session, person) if person else {"deleted": link_id}
