import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import get_engine, reset_engine_cache
from app.main import app
from app.models.evidence import Evidence


@pytest.fixture
def isolated_db(monkeypatch):
    monkeypatch.setenv("CASEMIND_DATABASE_URL", f"sqlite:///{tempfile.mktemp(suffix='.db')}")
    monkeypatch.setenv("CASEMIND_EVIDENCE_STORE", tempfile.mkdtemp())
    reset_engine_cache()
    yield
    reset_engine_cache()


def _seed(paths):
    with Session(get_engine()) as s:
        for i, p in enumerate(paths):
            s.add(Evidence(original_path=p, stored_path=f"store/{i}",
                           filename=f"f{i}", sha256=str(i)))
        s.commit()


def test_source_root_is_the_folder_holding_most_files(isolated_db):
    with TestClient(app) as client:
        _seed([
            r"\\NAS\share\case\a.txt",
            r"\\NAS\share\case\sub\b.txt",
            r"\\NAS\share\case\c.txt",
            r"D:\unrelated\x.txt",
        ])
        info = client.get("/admin/source-root").json()
        assert info["root"] == r"\\NAS\share\case"
        assert info["count"] == 3
        assert info["total"] == 4


def test_relocate_repoints_only_the_moved_folder(isolated_db):
    # the user moved a network folder to a local disk; re-point the recorded
    # source, leave evidence from other locations alone
    with TestClient(app) as client:
        _seed([
            r"\\NAS\share\case\a.txt",
            r"\\NAS\share\case\sub\b.txt",
            r"D:\other\keep.txt",
        ])
        res = client.post("/admin/relocate-source", json={
            "old_prefix": r"\\NAS\share\case", "new_prefix": r"E:\local\case"}).json()
        assert res["updated"] == 2

        with Session(get_engine()) as s:
            paths = sorted(e.original_path for e in s.exec(select(Evidence)).all())
        assert paths == [
            r"D:\other\keep.txt",           # untouched
            r"E:\local\case\a.txt",         # re-pointed
            r"E:\local\case\sub\b.txt",     # re-pointed, subfolder preserved
        ]


def test_relocate_matches_only_at_a_folder_boundary(isolated_db):
    # bug: startswith() matched any character, so re-pointing "C:\case" also
    # corrupted "C:\case2\..." and "C:\caseX" — unrelated folders
    with TestClient(app) as client:
        _seed([
            r"\\NAS\case\a.txt",       # under the folder -> rewrite
            r"\\NAS\case\sub\b.txt",   # under the folder -> rewrite
            r"\\NAS\case2\c.txt",      # DIFFERENT folder -> must NOT change
            r"\\NAS\caseX",            # DIFFERENT folder -> must NOT change
        ])
        res = client.post("/admin/relocate-source", json={
            "old_prefix": r"\\NAS\case", "new_prefix": r"E:\local"}).json()
        assert res["updated"] == 2

        with Session(get_engine()) as s:
            paths = sorted(e.original_path for e in s.exec(select(Evidence)).all())
        assert paths == [
            r"E:\local\a.txt",
            r"E:\local\sub\b.txt",
            r"\\NAS\case2\c.txt",   # untouched
            r"\\NAS\caseX",         # untouched
        ]


def test_relocate_rejects_empty_input(isolated_db):
    with TestClient(app) as client:
        _seed([r"\\NAS\share\a.txt"])
        r = client.post("/admin/relocate-source", json={"old_prefix": "", "new_prefix": "x"})
        assert r.status_code == 422
