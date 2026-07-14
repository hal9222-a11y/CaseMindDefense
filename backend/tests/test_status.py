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


def test_status_breakdown_accounts_for_every_file(tmp_path):
    # the "did it finish the material?" indicator: every file must land in
    # exactly one bucket, so a failure can never hide behind a green light
    with TestClient(app) as client:
        s = client.get("/status").json()
        buckets = s["processing"] + s["indexed"] + s["no_text"] + s["failed"]
        assert buckets == s["evidence_total"]
        assert s["failed"] >= 0


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
