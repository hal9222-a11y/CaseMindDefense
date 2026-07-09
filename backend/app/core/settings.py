from pathlib import Path
import os

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "CaseMind Defense API"

    database_url: str = os.getenv(
        "CASEMIND_DATABASE_URL",
        "sqlite:///./casemind_defense.db",
    )

    evidence_store_dir: Path = Path(
        os.getenv(
            "CASEMIND_EVIDENCE_STORE",
            "./data/evidence_store",
        )
    )


settings = Settings()