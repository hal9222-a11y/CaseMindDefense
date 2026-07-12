from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_session
from app.models.evidence import Case, Evidence, Person, PersonLink
from app.services.audit_service import log_event
from app.services.evidence_service import delete_evidence_record

router = APIRouter(prefix="/cases", tags=["cases"])


class CreateCaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.get("")
def list_cases(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    return session.exec(select(Case).order_by(Case.id).offset(offset).limit(limit)).all()


@router.post("")
def create_case(req: CreateCaseRequest, session: Session = Depends(get_session)):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="case name must not be blank")
    case = Case(name=name)
    session.add(case)
    session.commit()
    session.refresh(case)
    # build the payload before log_event: its commit expires the instance,
    # which would serialize as {}
    payload = {"id": case.id, "name": case.name, "created_at": case.created_at.isoformat()}
    log_event(session, "case_created", case_id=case.id, name=name)
    return payload


@router.delete("/{case_id}")
def delete_case(case_id: int, session: Session = Depends(get_session)):
    """Delete a case and every piece of evidence in it (files, chunks,
    entities, index). Irreversible — used when a matter is closed."""
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="case not found")

    evidence = session.exec(select(Evidence).where(Evidence.case_id == case_id)).all()
    for ev in evidence:
        delete_evidence_record(session, ev)

    # people and their links belong to the case too
    person_ids = session.exec(select(Person.id).where(Person.case_id == case_id)).all()
    if person_ids:
        for link in session.exec(
            select(PersonLink).where(PersonLink.person_id.in_(person_ids))
        ).all():
            session.delete(link)
        for person in session.exec(select(Person).where(Person.case_id == case_id)).all():
            session.delete(person)
        session.commit()

    name = case.name
    session.delete(case)
    session.commit()
    log_event(session, "case_deleted", case_id=case_id, name=name, evidence_count=len(evidence))
    return {"deleted": case_id, "evidence_deleted": len(evidence)}
