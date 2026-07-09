from fastapi import APIRouter, Depends
from sqlmodel import Session
from app.db import get_session
from app.services.entity_service import list_entities

router = APIRouter(prefix="/entities", tags=["entities"])

@router.get("")
def entities(session: Session = Depends(get_session)):
    return list_entities(session)
