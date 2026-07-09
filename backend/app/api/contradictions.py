from fastapi import APIRouter, Depends
from sqlmodel import Session
from app.db import get_session
from app.services.contradiction_service import find_contradictions

router = APIRouter(prefix="/contradictions", tags=["contradictions"])

@router.get("")
def contradictions(session: Session = Depends(get_session)):
    return find_contradictions(session)
