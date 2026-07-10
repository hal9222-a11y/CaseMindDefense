import hashlib
import json
import threading
from typing import Any

from sqlmodel import Session, select

from app.models.evidence import AuditEvent

# the chain read-last -> commit must be atomic: a request handler and a
# background indexing task logging concurrently would both read the same
# tail and fork the chain, making verify_audit_chain report a false break.
# ponytail: in-process lock (uvicorn runs one process); revisit for multi-worker
_chain_lock = threading.Lock()


def _hash_event(prev_hash: str, event: AuditEvent) -> str:
    # SQLite stores datetimes naive: strip tzinfo so the hash computed
    # before persisting matches the one recomputed after loading
    timestamp = event.created_at.replace(tzinfo=None).isoformat()
    payload = "|".join([
        prev_hash,
        event.event_type,
        str(event.evidence_id),
        timestamp,
        event.details_json,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def log_event(session: Session, event_type: str, evidence_id: int | None = None, **details: Any) -> AuditEvent:
    with _chain_lock:
        last = session.exec(
            select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1)
        ).first()
        prev_hash = last.event_hash if last else ""

        event = AuditEvent(
            event_type=event_type,
            evidence_id=evidence_id,
            details_json=json.dumps(details, ensure_ascii=False, default=str),
            prev_hash=prev_hash,
        )
        event.event_hash = _hash_event(prev_hash, event)
        session.add(event)
        session.commit()
    session.refresh(event)
    return event


def verify_audit_chain(session: Session) -> dict:
    """Walk the chain; recompute every hash. Legacy events (before the
    chain existed) have empty hashes and are only counted."""
    events = session.exec(select(AuditEvent).order_by(AuditEvent.id)).all()

    legacy = 0
    checked = 0
    prev_hash = ""
    for event in events:
        if not event.event_hash:
            legacy += 1
            continue
        expected = _hash_event(event.prev_hash, event)
        if event.event_hash != expected or event.prev_hash != prev_hash:
            return {
                "ok": False,
                "broken_at_id": event.id,
                "checked": checked,
                "legacy_unhashed": legacy,
            }
        prev_hash = event.event_hash
        checked += 1

    return {"ok": True, "broken_at_id": None, "checked": checked, "legacy_unhashed": legacy}
