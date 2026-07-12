from fastapi import APIRouter, Depends, Query
from sqlmodel import Session
from app.db import get_session
from app.services.search_service import search_chunks
from app.services.semantic_search_service import semantic_search

router = APIRouter(prefix="/search", tags=["search"])

@router.get("")
def search(
    q: str,
    limit: int = 10,
    case_id: int | None = Query(None),
    session: Session = Depends(get_session),
):
    return search_chunks(session, q, limit, case_id=case_id)

@router.get("/semantic")
def semantic(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    case_id: int | None = Query(None),
    session: Session = Depends(get_session),
):
    return semantic_search(session=session, query=q, limit=limit, case_id=case_id)
