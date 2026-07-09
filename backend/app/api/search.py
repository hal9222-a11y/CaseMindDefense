from fastapi import APIRouter, Depends, Query
from sqlmodel import Session
from app.db import get_session
from app.services.search_service import search_chunks
from app.services.semantic_search_service import semantic_search

router = APIRouter(prefix="/search", tags=["search"])

@router.get("")
def search(q: str, limit: int = 10, session: Session = Depends(get_session)):
    return search_chunks(session, q, limit)

@router.get("/semantic")
def semantic(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50), session: Session = Depends(get_session)):
    return semantic_search(session=session, query=q, limit=limit)
