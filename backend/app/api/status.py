from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.models.evidence import Evidence
from app.services import llm_service

router = APIRouter(tags=["status"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    """A cheap snapshot of what the system is doing right now — for the
    desktop activity indicator. Counts only, no heavy work."""
    total = session.exec(select(func.count()).select_from(Evidence)).one()
    processing = session.exec(
        select(func.count()).select_from(Evidence).where(Evidence.status == "processing")
    ).one()
    return {
        "ok": True,
        "evidence_total": total,
        "processing": processing,
        "busy": processing > 0,
        "llm_available": llm_service.ollama_available(),
        "llm_model": llm_service.LLM_MODEL,
    }
