from fastapi import APIRouter, Depends, Query
from sqlmodel import Session
from app.db import get_session
from app.services.contradiction_service import find_contradictions

router = APIRouter(prefix="/contradictions", tags=["contradictions"])

@router.get("")
def contradictions(
    case_id: int | None = Query(None),
    session: Session = Depends(get_session),
):
    return find_contradictions(session, case_id=case_id)
