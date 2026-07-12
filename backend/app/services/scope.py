from __future__ import annotations

from sqlmodel import Session, select

from app.models.evidence import Evidence


def case_evidence_ids(session: Session, case_id: int | None) -> set[int] | None:
    """Evidence ids belonging to a case, or None for 'all cases' (no filter).

    Analysis services use this to keep one case's material from bleeding into
    another's search / timeline / entities / contradictions when several
    cases share the database."""
    if case_id is None:
        return None
    return set(session.exec(select(Evidence.id).where(Evidence.case_id == case_id)).all())
