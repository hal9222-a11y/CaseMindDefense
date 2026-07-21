import os
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_stored_path_is_absolute_and_openable_from_any_cwd(tmp_path):
    # the desktop opens the stored file itself and runs from a different working
    # directory than the backend; a relative path became "file not found"
    with TestClient(app) as client:
        src = tmp_path / f"doc_{uuid.uuid4().hex}.txt"
        src.write_text("evidence body", encoding="utf-8")
        ev = client.post("/evidence/import-file", json={"path": str(src)}).json()

        stored = ev["stored_path"]
        assert os.path.isabs(stored), stored

        # simulate the desktop: a completely different working directory
        original = os.getcwd()
        try:
            os.chdir(tmp_path)
            assert Path(stored).exists(), "the desktop cannot open the stored file"
        finally:
            os.chdir(original)


def test_the_browser_never_silently_drops_evidence(tmp_path):
    # a case with 108 files showed only 100: the server default limit truncated
    # the list, so 8 files were invisible and citations into them failed
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"c_{uuid.uuid4().hex}"}).json()
        created = []
        for i in range(12):
            p = tmp_path / f"f_{i}_{uuid.uuid4().hex}.txt"
            p.write_text(f"file number {i}", encoding="utf-8")
            r = client.post(
                "/evidence/import-file", json={"path": str(p), "case_id": case["id"]}
            )
            created.append(r.json()["id"])

        # the client asks for everything, not the server default page
        listed = client.get(
            "/evidence", params={"case_id": case["id"], "limit": 20000}
        ).json()
        assert {e["id"] for e in listed} == set(created)

        # and the server is willing to serve far past the old 1000 ceiling
        assert client.get("/evidence", params={"limit": 20000}).status_code == 200


def test_evidence_list_does_not_ship_translations():
    """The list once returned raw Evidence rows — including each row's full
    precomputed `translation` text (up to ~80k chars) on every refresh. The UI
    reads translations only from /evidence/{id}/content."""
    import uuid as _uuid

    from sqlmodel import Session

    from app.db import get_engine, init_db
    from app.models.evidence import Evidence

    init_db()
    with Session(get_engine()) as s:
        ev = Evidence(
            original_path="x", stored_path="C:\\x", filename="ru_doc.txt",
            sha256=_uuid.uuid4().hex, size_bytes=1, status="indexed",
            translation="תרגום ארוך מאוד " * 1000, translation_status="done",
        )
        s.add(ev)
        s.commit()
        s.refresh(ev)
        ev_id = ev.id

    with TestClient(app) as client:
        rows = client.get("/evidence", params={"limit": 20000}).json()
        row = next(r for r in rows if r["id"] == ev_id)
        assert "translation" not in row and "translation_chunks_done" not in row
        # the fields the desktop actually reads are all present
        assert {"id", "case_id", "filename", "status", "size_bytes",
                "mime_type", "imported_at", "stored_path"} <= set(row)
