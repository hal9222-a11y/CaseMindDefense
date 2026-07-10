from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_session
from app.models.evidence import Case
from app.services.audit_service import log_event

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
