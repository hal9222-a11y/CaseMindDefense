from fastapi import APIRouter, Depends, Query
from sqlmodel import Session
from app.db import get_session
from app.services.entity_service import list_entities

router = APIRouter(prefix="/entities", tags=["entities"])

@router.get("")
def entities(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    return list_entities(session)[offset : offset + limit]
