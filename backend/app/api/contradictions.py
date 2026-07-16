from fastapi import APIRouter, Depends, Query
from sqlmodel import Session
from app.db import get_session
from app.services.contradiction_service import find_contradictions
from app.services.claim_contradiction_service import analyze_claims

router = APIRouter(prefix="/contradictions", tags=["contradictions"])

@router.get("")
def contradictions(
    case_id: int | None = Query(None),
    session: Session = Depends(get_session),
):
    return find_contradictions(session, case_id=case_id)


@router.get("/claims")
def claim_contradictions(
    case_id: int | None = Query(None),
    evidence_ids: str | None = Query(None, description="comma-separated evidence ids to cross-check"),
    session: Session = Depends(get_session),
):
    """Claim-level engine: decomposes statements into atomic claims and finds
    contradictions across sources (denial vs. records, time gaps, etc.) that
    similarity search misses."""
    ids = [int(x) for x in evidence_ids.split(",") if x.strip().isdigit()] if evidence_ids else None
    return analyze_claims(session, case_id=case_id, evidence_ids=ids)
