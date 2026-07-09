from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.db import get_session
from app.models.evidence import AuditEvent

router = APIRouter(prefix="/audit", tags=["audit"])

@router.get("")
def list_audit(session: Session = Depends(get_session)):
    return session.exec(select(AuditEvent)).all()
