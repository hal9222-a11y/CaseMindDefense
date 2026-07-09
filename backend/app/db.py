from functools import lru_cache

from sqlmodel import SQLModel, Session, create_engine

from app.core.settings import Settings


@lru_cache(maxsize=1)
def get_engine():
    settings = Settings()

    return create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )


def reset_engine_cache() -> None:
    get_engine.cache_clear()


def _migrate_evidencechunk_columns(engine) -> None:
    # ponytail: naive ALTER-based migration; switch to Alembic if schema churn grows
    new_columns = {
        "embedding_model": "TEXT NOT NULL DEFAULT ''",
        "embedding_dimension": "INTEGER NOT NULL DEFAULT 0",
        "embedding_version": "TEXT NOT NULL DEFAULT '1'",
    }
    with engine.connect() as conn:
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(evidencechunk)")}
        if not existing:
            return  # table not created yet; create_all will build it complete
        for name, ddl in new_columns.items():
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE evidencechunk ADD COLUMN {name} {ddl}")
        conn.commit()


def init_db() -> None:
    from app.models.evidence import AuditEvent, Evidence, EvidenceChunk  # noqa

    engine = get_engine()
    _migrate_evidencechunk_columns(engine)
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(get_engine()) as session:
        yield session