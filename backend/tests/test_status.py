import uuid

from fastapi.testclient import TestClient

from app.main import app


def test_status_reports_counts_and_readiness(tmp_path):
    with TestClient(app) as client:
        s = client.get("/status").json()
        assert s["ok"] is True
        assert "evidence_total" in s and "processing" in s
        assert "busy" in s and "llm_available" in s
        assert isinstance(s["busy"], bool)


def test_status_busy_reflects_processing(tmp_path):
    from sqlmodel import Session
    from app.db import get_engine
    from app.models.evidence import Evidence

    with TestClient(app) as client:
        p = tmp_path / f"s_{uuid.uuid4().hex}.txt"
        p.write_text("busy check", encoding="utf-8")
        ev = client.post("/evidence/import-file", json={"path": str(p)}).json()
        # force it to processing to simulate an in-flight batch
        with Session(get_engine()) as session:
            row = session.get(Evidence, ev["id"])
            row.status = "processing"
            session.add(row)
            session.commit()
        s = client.get("/status").json()
        assert s["busy"] is True and s["processing"] >= 1

        client.delete(f"/evidence/{ev['id']}")
