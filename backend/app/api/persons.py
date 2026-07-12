from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_session
from app.models.evidence import Case, Evidence, Person, PersonLink
from app.services.audit_service import log_event
from app.services.person_service import suggest_phone_links

router = APIRouter(prefix="/persons", tags=["persons"])

LINK_KINDS = {"alias", "phone", "photo", "relation"}


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
