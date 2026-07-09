import json
from typing import Any
from sqlmodel import Session
from app.models.evidence import AuditEvent

def log_event(session: Session, event_type: str, evidence_id: int | None = None, **details: Any) -> AuditEvent:
    event = AuditEvent(
        event_type=event_type,
        evidence_id=evidence_id,
        details_json=json.dumps(details, ensure_ascii=False, default=str),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event
