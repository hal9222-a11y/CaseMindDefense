"""A backup must never fill the drive it protects: /admin/backup refuses up
front when the evidence + DB won't fit with margin, and leaves no stray zip."""
import shutil
import types

from fastapi.testclient import TestClient

from app.main import app
from app.core.settings import get_settings


def _backups_dir():
    store = get_settings().evidence_store_dir
    return store.parent / "backups"


def test_backup_refused_when_disk_nearly_full(monkeypatch):
    # pretend the drive is essentially full — below even the tiny test DB
    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda _p: types.SimpleNamespace(total=1, used=1, free=0),
    )
    with TestClient(app) as client:
        before = set(_backups_dir().glob("*.zip")) if _backups_dir().exists() else set()
        r = client.post("/admin/backup")
        assert r.status_code == 507
        after = set(_backups_dir().glob("*.zip")) if _backups_dir().exists() else set()
        assert before == after  # no half-written zip left behind


def test_backup_succeeds_with_space():
    # real disk_usage (plenty free on the test drive); tiny empty store
    with TestClient(app) as client:
        r = client.post("/admin/backup")
        assert r.status_code == 200
        assert r.json()["size_bytes"] > 0
