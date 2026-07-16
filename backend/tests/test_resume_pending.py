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


def test_resume_survives_disk_io_errors(tmp_path, monkeypatch):
    """The evidence DB lives on a flaky drive. A transient disk I/O error used
    to kill the resume loop silently — the queue then sat idle until the next
    restart. The loop must reconnect and finish the item instead."""
    import uuid as _uuid

    from sqlalchemy.exc import OperationalError
    from fastapi.testclient import TestClient
    from sqlmodel import Session

    from app.main import app
    from app.db import get_engine
    from app.models.evidence import Evidence
    from app.services import evidence_service
    from app.services.evidence_service import resume_pending_indexing

    with TestClient(app) as client:
        p = tmp_path / f"flaky_{_uuid.uuid4().hex}.txt"
        p.write_text("evidence on a flaky drive", encoding="utf-8")
        ev = client.post("/evidence/import-file", json={"path": str(p)}).json()
        with Session(get_engine()) as session:
            row = session.get(Evidence, ev["id"])
            row.status = "processing"
            session.add(row)
            session.commit()

        real_index = evidence_service.index_evidence
        failures = iter([True, True])  # first two attempts hit the "drive"

        def flaky_index(session, evidence_id):
            if next(failures, False):
                raise OperationalError("SELECT 1", {}, Exception("disk I/O error"))
            return real_index(session, evidence_id)

        monkeypatch.setattr(evidence_service, "index_evidence", flaky_index)
        monkeypatch.setattr("time.sleep", lambda s: None)  # no real 15s waits in tests

        assert resume_pending_indexing() == 1  # survived both dropouts, indexed the item
        with Session(get_engine()) as session:
            assert session.get(Evidence, ev["id"]).status == "indexed"
