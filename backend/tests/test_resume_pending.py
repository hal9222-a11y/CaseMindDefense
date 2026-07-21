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


def test_resume_processes_a_multi_item_queue_once_each(monkeypatch):
    """A done row is dropped from `attempted` (it no longer matches
    status=='processing'), so the set the NOT-IN query feeds stays bounded on a
    long queue. Mocks the indexer (no GPU) to exercise the loop itself: every
    item must index exactly once and the loop must terminate — a re-process bug
    would loop forever, an over-eager skip would leave items unprocessed."""
    from app.db import init_db
    from app.services import evidence_service

    init_db()  # create tables without the app lifespan (no model warmup / GPU)
    with Session(get_engine()) as session:
        ids = []
        for i in range(6):
            ev = Evidence(
                original_path=f"x{i}", stored_path=f"x{i}", filename=f"x{i}.txt",
                sha256=uuid.uuid4().hex, size_bytes=1, mime_type="text/plain",
                status="processing",
            )
            session.add(ev)
            session.commit()
            session.refresh(ev)
            ids.append(ev.id)

    calls: list[int] = []

    def stub_index(session, evidence_id):
        calls.append(evidence_id)
        row = session.get(Evidence, evidence_id)
        row.status = "indexed"  # terminal status -> no longer 'processing'
        session.add(row)
        session.commit()

    monkeypatch.setattr(evidence_service, "index_evidence", stub_index)

    processed = resume_pending_indexing()
    assert processed == 6                 # every queued item, none skipped
    assert sorted(calls) == sorted(ids)   # each processed EXACTLY once, loop terminated


def test_resume_requeues_transcription_unavailable(monkeypatch):
    """A file marked 'transcription_unavailable' (Whisper couldn't load — usually
    a transient GPU/drive blip) must not be stranded forever: resume requeues it
    so it retries once the model is back."""
    from app.db import init_db
    from app.services import evidence_service

    init_db()
    with Session(get_engine()) as session:
        ev = Evidence(
            original_path="voice", stored_path="voice.opus", filename="voice.opus",
            sha256=uuid.uuid4().hex, size_bytes=1, mime_type="audio/opus",
            status="transcription_unavailable",
        )
        session.add(ev)
        session.commit()
        session.refresh(ev)
        ev_id = ev.id

    def stub_index(session, evidence_id):
        row = session.get(Evidence, evidence_id)
        row.status = "transcribed"  # Whisper is back now
        session.add(row)
        session.commit()

    monkeypatch.setattr(evidence_service, "index_evidence", stub_index)

    resume_pending_indexing()
    with Session(get_engine()) as session:
        assert session.get(Evidence, ev_id).status == "transcribed"  # retried, not stranded


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
