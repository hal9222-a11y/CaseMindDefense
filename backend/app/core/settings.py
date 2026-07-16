from pathlib import Path
import os

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = "CaseMind Defense API"

    # default_factory: read env at instantiation time, not import time,
    # so test fixtures can override CASEMIND_* before the engine is built
    database_url: str = Field(default_factory=lambda: _database_url())

    # resolved to an absolute path: the desktop reads stored files straight off
    # disk, and it runs from a different working directory than the backend — a
    # relative path silently became "file not found" in the preview
    evidence_store_dir: Path = Field(default_factory=lambda: _evidence_store_dir())


def _database_url(redirect: Path | None = None) -> str:
    """Same env-else-redirect-else-default scheme as the evidence store, for the
    same reason: the desktop revives a dead backend with the DESKTOP's env, so an
    env-only relocation would silently flip a revived backend back to the old
    (flaky) drive. data/database.path holds a plain filesystem path to the .db.
    `redirect` is injectable for tests; production always uses the repo file."""
    env = os.getenv("CASEMIND_DATABASE_URL")
    if env:
        return env
    if redirect is None:
        redirect = Path(__file__).resolve().parents[2] / "data" / "database.path"
    if redirect.exists():
        target = redirect.read_text(encoding="utf-8").strip()
        if target:
            target_path = Path(target).resolve()
            if not target_path.exists():
                # A relocated DB that is missing means the drive is unplugged or the
                # redirect is stale. Connecting anyway would silently CREATE a new
                # empty DB there (or fail cryptically) — the case would look wiped
                # and new evidence would fork into an orphan file. Die loudly instead.
                raise RuntimeError(
                    f"database.path points to {target_path} but no file exists there. "
                    "Reconnect the drive, or fix/delete backend/data/database.path."
                )
            return f"sqlite:///{target_path.as_posix()}"
    return "sqlite:///./casemind_defense.db"


def _evidence_store_dir() -> Path:
    """Where the evidence store lives: env override, else a redirect file, else
    the in-repo default. The redirect file exists because the desktop revives a
    dead backend with the DESKTOP's environment — an env-only relocation would
    silently flip a revived backend back to the old (possibly full) drive and
    write new evidence there."""
    env = os.getenv("CASEMIND_EVIDENCE_STORE")
    if env:
        return Path(env).resolve()
    redirect = Path(__file__).resolve().parents[2] / "data" / "evidence_store.path"
    if redirect.exists():
        target = redirect.read_text(encoding="utf-8").strip()
        if target:
            return Path(target).resolve()
    return Path("./data/evidence_store").resolve()


def get_settings() -> Settings:
    return Settings()
