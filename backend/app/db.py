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


# ponytail: naive ALTER-based migrations; switch to Alembic if schema churn grows
_MIGRATIONS = {
    "evidencechunk": {
        "embedding_model": "TEXT NOT NULL DEFAULT ''",
        "embedding_dimension": "INTEGER NOT NULL DEFAULT 0",
        "embedding_version": "TEXT NOT NULL DEFAULT '1'",
    },
    "evidence": {
        "case_id": "INTEGER",
    },
    "auditevent": {
        "prev_hash": "TEXT NOT NULL DEFAULT ''",
        "event_hash": "TEXT NOT NULL DEFAULT ''",
    },
}


def _migrate_columns(engine) -> None:
    with engine.connect() as conn:
        for table, new_columns in _MIGRATIONS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if not existing:
                continue  # table not created yet; create_all will build it complete
            for name, ddl in new_columns.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        conn.commit()


def _init_fts(engine) -> None:
    """FTS5 index over chunk text, kept in sync by triggers. If this SQLite
    build lacks FTS5, keyword search falls back to LIKE."""
    with engine.connect() as conn:
        already = conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
        ).fetchone()
        try:
            conn.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5("
                "text, content='evidencechunk', content_rowid='id')"
            )
        except Exception:
            return  # no FTS5 in this build; LIKE fallback covers search
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS evidencechunk_fts_ai "
            "AFTER INSERT ON evidencechunk BEGIN "
            "INSERT INTO chunk_fts(rowid, text) VALUES (new.id, new.text); END"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS evidencechunk_fts_ad "
            "AFTER DELETE ON evidencechunk BEGIN "
            "INSERT INTO chunk_fts(chunk_fts, rowid, text) "
            "VALUES ('delete', old.id, old.text); END"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS evidencechunk_fts_au "
            "AFTER UPDATE ON evidencechunk BEGIN "
            "INSERT INTO chunk_fts(chunk_fts, rowid, text) "
            "VALUES ('delete', old.id, old.text); "
            "INSERT INTO chunk_fts(rowid, text) VALUES (new.id, new.text); END"
        )
        if not already:
            # first creation on an existing DB: index pre-existing chunks
            conn.exec_driver_sql("INSERT INTO chunk_fts(chunk_fts) VALUES ('rebuild')")
        conn.commit()


def init_db() -> None:
    from app.models.evidence import AuditEvent, Case, Evidence, EvidenceChunk  # noqa

    engine = get_engine()
    _migrate_columns(engine)
    SQLModel.metadata.create_all(engine)
    _init_fts(engine)


def get_session():
    with Session(get_engine()) as session:
        yield session