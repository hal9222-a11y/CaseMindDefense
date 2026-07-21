import uuid
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_api_key_enforced_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("CASEMIND_API_KEY", "secret-key-123")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200  # liveness stays open
        assert client.get("/evidence").status_code == 401
        assert client.get("/evidence", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get("/evidence", headers={"X-API-Key": "secret-key-123"}).status_code == 200


def test_open_mode_without_key(monkeypatch):
    monkeypatch.delenv("CASEMIND_API_KEY", raising=False)
    with TestClient(app) as client:
        assert client.get("/evidence").status_code == 200


def test_import_roots_allowlist(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("CASEMIND_IMPORT_ROOTS", str(allowed))

    inside_file = allowed / f"ok_{uuid.uuid4().hex}.txt"
    inside_file.write_text("fine", encoding="utf-8")
    outside_file = outside / f"blocked_{uuid.uuid4().hex}.txt"
    outside_file.write_text("nope", encoding="utf-8")

    with TestClient(app) as client:
        assert client.post("/evidence/import-file", json={"path": str(inside_file)}).status_code == 200
        assert client.post("/evidence/import-file", json={"path": str(outside_file)}).status_code == 403


def test_integrity_check_detects_tampering(tmp_path):
    with TestClient(app) as client:
        p = tmp_path / f"tamper_{uuid.uuid4().hex}.txt"
        p.write_text("original content", encoding="utf-8")
        ev = client.post("/evidence/import-file", json={"path": str(p)}).json()

        # our evidence must be clean before tampering (global ok would couple
        # this test to leftovers from unrelated tests)
        before = client.post("/admin/verify-evidence").json()
        assert not any(t["id"] == ev["id"] for t in before["tampered"] + before["missing"])

        stored = Path(client.get(f"/evidence/{ev['id']}").json()["stored_path"])
        stored.write_text("EVIDENCE MODIFIED", encoding="utf-8")

        result = client.post("/admin/verify-evidence").json()
        assert result["ok"] is False
        assert any(t["id"] == ev["id"] for t in result["tampered"])

        client.delete(f"/evidence/{ev['id']}")  # cleanup for other tests


def test_backup_creates_zip_with_db_and_store(tmp_path):
    with TestClient(app) as client:
        p = tmp_path / f"backup_{uuid.uuid4().hex}.txt"
        p.write_text("back me up", encoding="utf-8")
        client.post("/evidence/import-file", json={"path": str(p)})

        result = client.post("/admin/backup").json()
        zip_path = Path(result["path"])
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert "casemind_defense.db" in names
        assert any(n.startswith("evidence_store/") for n in names)
        assert result["evidence_files"] >= 1


def test_import_roots_always_allow_the_evidence_store(tmp_path, monkeypatch):
    """The UFDR media extractor stages temp files inside the evidence store
    before registering them. An import allowlist that doesn't mention the store
    used to break extraction entirely — the store is our own custody area and
    must always be an allowed source."""
    import uuid as _uuid

    from app.core.settings import get_settings
    from app.services.evidence_service import _check_import_allowed, ImportPathNotAllowedError

    monkeypatch.setenv("CASEMIND_IMPORT_ROOTS", str(tmp_path / "some_allowed_root"))

    store_file = get_settings().evidence_store_dir / f"staged_{_uuid.uuid4().hex}.opus"
    store_file.parent.mkdir(parents=True, exist_ok=True)
    store_file.write_bytes(b"x" * 10)
    _check_import_allowed(store_file)  # must NOT raise

    outside = tmp_path / f"outside_{_uuid.uuid4().hex}.txt"
    outside.write_text("nope", encoding="utf-8")
    try:
        _check_import_allowed(outside)
        raise AssertionError("outside path must be rejected")
    except ImportPathNotAllowedError:
        pass
    store_file.unlink()


def test_database_redirect_refuses_missing_target(tmp_path, monkeypatch):
    """A stale/unplugged database.path must fail LOUDLY: silently connecting
    would create a fresh empty DB and the whole case would look wiped."""
    import pytest

    from app.core.settings import _database_url

    monkeypatch.delenv("CASEMIND_DATABASE_URL", raising=False)
    redirect = tmp_path / "database.path"
    redirect.write_text(str(tmp_path / "no_such_dir" / "gone.db"), encoding="utf-8")

    with pytest.raises(RuntimeError, match="no file exists"):
        _database_url(redirect=redirect)

    # and a redirect whose target DOES exist resolves to it
    db = tmp_path / "real.db"
    db.write_bytes(b"")
    redirect.write_text(str(db), encoding="utf-8")
    assert _database_url(redirect=redirect) == f"sqlite:///{db.resolve().as_posix()}"
