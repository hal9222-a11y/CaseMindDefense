import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import get_engine
from app.main import app
from app.models.evidence import AuditEvent


def test_audit_chain_valid_after_activity(tmp_path):
    with TestClient(app) as client:
        p = tmp_path / f"chain_{uuid.uuid4().hex}.txt"
        p.write_text("chained evidence", encoding="utf-8")
        client.post("/evidence/import-file", json={"path": str(p)})

        result = client.post("/admin/verify-audit").json()
        assert result["ok"] is True
        assert result["checked"] >= 2  # imported + indexed at minimum


def test_audit_chain_detects_tampering(tmp_path):
    with TestClient(app) as client:
        p = tmp_path / f"tamperlog_{uuid.uuid4().hex}.txt"
        p.write_text("audit me", encoding="utf-8")
        client.post("/evidence/import-file", json={"path": str(p)})

        # rewrite history: change the details of an old hashed event
        with Session(get_engine()) as session:
            event = session.exec(
                select(AuditEvent)
                .where(AuditEvent.event_hash != "")
                .order_by(AuditEvent.id)
            ).first()
            event_id = event.id
            session.connection().exec_driver_sql(
                "UPDATE auditevent SET details_json = ? WHERE id = ?",
                ('{"forged": true}', event_id),
            )
            session.commit()

        result = client.post("/admin/verify-audit").json()
        assert result["ok"] is False
        assert result["broken_at_id"] == event_id
