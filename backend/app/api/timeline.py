from fastapi import APIRouter, Depends
from sqlmodel import Session
from app.db import get_session
from app.services.timeline_service import build_timeline

router = APIRouter(prefix="/timeline", tags=["timeline"])

@router.get("")
def timeline(session: Session = Depends(get_session)):
    return build_timeline(session)
