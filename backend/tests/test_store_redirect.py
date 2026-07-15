"""The evidence store location must survive a backend revived with a stale
environment: env var wins, then the data/evidence_store.path redirect file,
then the in-repo default."""
from pathlib import Path

from app.core import settings as settings_mod


def test_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("CASEMIND_EVIDENCE_STORE", str(tmp_path / "env_store"))
    assert settings_mod._evidence_store_dir() == (tmp_path / "env_store").resolve()


def test_redirect_file_used_when_no_env(monkeypatch, tmp_path):
    monkeypatch.delenv("CASEMIND_EVIDENCE_STORE", raising=False)
    redirect = Path(settings_mod.__file__).resolve().parents[2] / "data" / "evidence_store.path"
    had = redirect.exists()
    original = redirect.read_text(encoding="utf-8") if had else None
    try:
        redirect.parent.mkdir(parents=True, exist_ok=True)
        redirect.write_text(str(tmp_path / "moved_store"), encoding="utf-8")
        assert settings_mod._evidence_store_dir() == (tmp_path / "moved_store").resolve()
        # an empty redirect must fall back to the default, not Path(".")
        redirect.write_text("", encoding="utf-8")
        assert settings_mod._evidence_store_dir().name == "evidence_store"
    finally:
        if had:
            redirect.write_text(original, encoding="utf-8")
        else:
            redirect.unlink(missing_ok=True)
