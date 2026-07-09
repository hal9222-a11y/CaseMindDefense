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

    evidence_store_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "CASEMIND_EVIDENCE_STORE",
                "./data/evidence_store",
            )
        )
    )


def get_settings() -> Settings:
    return Settings()
