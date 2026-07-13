import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import get_engine
from app.main import app
from app.models.evidence import Evidence
from app.services.evidence_service import resume_pending_indexing


def test_resume_reindexes_orphaned_processing(tmp_path):
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        p = tmp_path / f"orphan_{marker}.txt"
        p.write_text(f"stranded evidence {marker}", encoding="utf-8")
        ev = client.post("/evidence/import-file", json={"path": str(p)}).json()

        # simulate a crash: force the item back to 'processing' as if the
        # indexing task had died before finishing
        with Session(get_engine()) as session:
            row = session.get(Evidence, ev["id"])
            row.status = "processing"
            session.add(row)
            session.commit()

        assert resume_pending_indexing() >= 1
        assert client.get(f"/evidence/{ev['id']}").json()["status"] == "indexed"
        assert len(client.get("/search", params={"q": marker}).json()) == 1

        client.delete(f"/evidence/{ev['id']}")


def test_reindex_pending_endpoint(tmp_path):
    with TestClient(app) as client:
        r = client.post("/admin/reindex-pending")
        assert r.status_code == 200
        assert "pending" in r.json()
