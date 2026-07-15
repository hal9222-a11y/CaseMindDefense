from pathlib import Path
import os

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = "CaseMind Defense API"

    # default_factory: read env at instantiation time, not import time,
    # so test fixtures can override CASEMIND_* before the engine is built
    database_url: str = Field(
        default_factory=lambda: os.getenv(
            "CASEMIND_DATABASE_URL",
            "sqlite:///./casemind_defense.db",
        )
    )

    # resolved to an absolute path: the desktop reads stored files straight off
    # disk, and it runs from a different working directory than the backend — a
    # relative path silently became "file not found" in the preview
    evidence_store_dir: Path = Field(default_factory=lambda: _evidence_store_dir())


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
