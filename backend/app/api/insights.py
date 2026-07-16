"""Case-level AI insights: the "help us understand the material" endpoints.
Everything here is grounded in the case's own text and is an orientation aid,
not evidence — the underlying chunks stay the source of truth."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models.evidence import Evidence

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/case-summary")
def case_summary(case_id: int = Query(...), session: Session = Depends(get_session)):
    """A whole-case overview: what it's about, the main people, recurring
    themes, and things to check — grounded in a representative sample."""
    from app.services.case_analysis_service import case_overview

    return case_overview(session, case_id)


@router.get("/questions")
def questions(case_id: int = Query(...), session: Session = Depends(get_session)):
    """Investigator questions the material suggests looking into."""
    from app.services.case_analysis_service import suggest_questions

    return suggest_questions(session, case_id)


@router.get("/weaknesses")
def weaknesses(case_id: int = Query(...), session: Session = Depends(get_session)):
    """Defense-lens case weaknesses: contradictions, evidentiary gaps,
    reliability problems, alternative readings — grounded in a sample and
    framed by the user's declared role (PATCH /cases/{id})."""
    from app.services.case_analysis_service import find_weaknesses

    return find_weaknesses(session, case_id)


@router.get("/flags")
def flags(case_id: int = Query(...), session: Session = Depends(get_session)):
    """Passages matching sensitive categories (money/drugs/weapons/threats),
    each cited. Deterministic and offline — no LLM needed."""
    from app.services.flag_service import flag_summary, scan_flags

    return {"summary": flag_summary(session, case_id), "flags": scan_flags(session, case_id)}


@router.get("/events")
def events(case_id: int = Query(...), session: Session = Depends(get_session)):
    """AI-extracted dated events ('who did what when') with citations."""
    from app.services.event_service import extract_events

    return extract_events(session, case_id)


@router.get("/duplicates")
def duplicates(case_id: int = Query(...), session: Session = Depends(get_session)):
    """Evidence items that carry the same content in different containers (the
    same chat as PDF and TXT) — which SHA256 dedup misses. Reports groups for
    review; nothing is deleted."""
    from app.services.dedup_service import find_duplicates

    groups = find_duplicates(session, case_id)
    return {"groups": groups, "count": len(groups)}


@router.get("/recordings-digest")
def recordings_digest(case_id: int = Query(...), session: Session = Depends(get_session)):
    """One-line-per-recording digest: for each transcribed audio/video item,
    its people and a short AI summary — so a wall of call recordings becomes a
    scannable list. Reuses per-evidence summarization."""
    from app.services.summary_service import summarize_evidence

    transcribed = session.exec(
        select(Evidence).where(
            Evidence.case_id == case_id, Evidence.status == "transcribed"
        ).order_by(Evidence.id)
    ).all()
    # bounded so the endpoint returns in reasonable time; the UI can paginate
    digest = []
    for ev in transcribed[:25]:
        result = summarize_evidence(session, ev.id)
        digest.append({
            "evidence_id": ev.id,
            "filename": ev.filename,
            "people": result.get("people", []),
            "summary": result.get("summary"),
            "reason": result.get("reason"),
        })
    return {"count": len(transcribed), "shown": len(digest), "digest": digest}
