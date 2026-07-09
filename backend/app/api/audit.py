from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select
from app.db import get_session
from app.models.evidence import AuditEvent

router = APIRouter(prefix="/audit", tags=["audit"])

@router.get("")
def list_audit(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    return session.exec(
        select(AuditEvent).order_by(AuditEvent.id.desc()).offset(offset).limit(limit)
    ).all()
