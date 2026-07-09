from functools import lru_cache

from sqlmodel import SQLModel, Session, create_engine

from app.core.settings import Settings, settings


@lru_cache(maxsize=1)
def get_engine():
    return create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )


def reset_engine_cache() -> None:
    get_engine.cache_clear()


def init_db() -> None:
    from app.models.evidence import AuditEvent, Evidence, EvidenceChunk  # noqa

    SQLModel.metadata.create_all(get_engine())


def get_session():
    with Session(get_engine()) as session:
        yield session