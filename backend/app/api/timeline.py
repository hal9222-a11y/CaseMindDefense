from fastapi import APIRouter, Depends, Query
from sqlmodel import Session
from app.db import get_session
from app.services.timeline_service import build_timeline

router = APIRouter(prefix="/timeline", tags=["timeline"])

@router.get("")
def timeline(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    return build_timeline(session)[offset : offset + limit]
