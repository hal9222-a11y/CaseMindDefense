import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import get_engine, reset_engine_cache
from app.main import app
from app.models.evidence import AuditEvent
from app.services.audit_service import verify_audit_chain


@pytest.fixture
def isolated_db(monkeypatch):
    """A fresh database per test. These tests tamper with the audit log, so they
    must not run against the shared test DB or they poison every later test."""
    monkeypatch.setenv("CASEMIND_DATABASE_URL", f"sqlite:///{tempfile.mktemp(suffix='.db')}")
    monkeypatch.setenv("CASEMIND_EVIDENCE_STORE", tempfile.mkdtemp())
    reset_engine_cache()
    yield
    reset_engine_cache()


def _one_import(client):
    path = tempfile.mktemp(suffix=".txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("evidence body")
    assert client.post("/evidence/import-file", json={"path": path}).status_code == 200


def test_a_clean_chain_verifies_fully(isolated_db):
    with TestClient(app) as client:
        _one_import(client)
        with Session(get_engine()) as session:
            result = verify_audit_chain(session)
    assert result["ok"] is True
    assert result["broken_at_id"] is None
    assert result["legacy_unverifiable"] == 0
    assert result["checked"] >= 2


def test_editing_a_hashed_event_is_detected(isolated_db):
    with TestClient(app) as client:
        _one_import(client)
        with Session(get_engine()) as session:
            target = session.exec(
                select(AuditEvent).where(AuditEvent.event_hash != "").order_by(AuditEvent.id)
            ).first()
            target.event_type = "evidence_deleted"   # doctor a real record
            session.add(target)
            session.commit()
            result = verify_audit_chain(session)
    assert result["ok"] is False
    assert result["reason"] == "tampered"
    assert result["broken_at_id"] == target.id


def test_unverifiable_legacy_records_are_not_reported_as_ok(isolated_db):
    # the bug: a doctored LEGACY record (no hash) returned ok=True, because the
    # verifier skipped it silently. A tamper-evidence tool must not claim the
    # trail is intact when part of it cannot be checked.
    with TestClient(app):
        with Session(get_engine()) as session:
            session.add(AuditEvent(event_type="legacy_thing", event_hash="", prev_hash=""))
            session.commit()
            result = verify_audit_chain(session)
    assert result["ok"] is False
    assert result["reason"] == "unverifiable_legacy_records"
    assert result["legacy_unverifiable"] >= 1
