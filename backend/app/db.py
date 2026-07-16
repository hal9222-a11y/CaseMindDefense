from functools import lru_cache

from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine

from app.core.settings import Settings


@lru_cache(maxsize=1)
def get_engine():
    settings = Settings()

    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        # The DB lives on a drive that drops out for seconds at a time. A dropout
        # permanently poisons the pooled SQLite connections ("disk I/O error" on
        # every later call) — the pool then recycles the corpse forever and every
        # worker dies. pre_ping tests each connection before use and replaces
        # broken ones, so a drive hiccup costs one retry instead of the whole queue.
        pool_pre_ping=True,
    )

    # This app runs many concurrent SQLite connections — request handlers, the
    # background indexer, the startup resume daemon, the 4s /status poll. In the
    # default rollback-journal mode with busy_timeout=0, any lock contention
    # raises "database is locked" (a 500) instantly. WAL lets readers run
    # alongside the single writer, and busy_timeout makes a contended write wait
    # instead of failing. WAL is persistent and the backup uses the sqlite
    # backup API, so snapshots stay consistent.
    if settings.database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    return engine


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
        "translation_status": "TEXT NOT NULL DEFAULT ''",
        "translation": "TEXT NOT NULL DEFAULT ''",
        "translation_chunks_done": "INTEGER NOT NULL DEFAULT 0",
    },
    "auditevent": {
        "prev_hash": "TEXT NOT NULL DEFAULT ''",
        "event_hash": "TEXT NOT NULL DEFAULT ''",
    },
    "case": {
        "role_context": "TEXT NOT NULL DEFAULT ''",
    },
}


def _migrate_columns(engine) -> None:
    with engine.connect() as conn:
        for table, new_columns in _MIGRATIONS.items():
            # quoted: "case" is a reserved SQL keyword
            existing = {row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table}")')}
            if not existing:
                continue  # table not created yet; create_all will build it complete
            for name, ddl in new_columns.items():
                if name not in existing:
                    conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN {name} {ddl}')
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
    from app.models.evidence import (  # noqa
        AuditEvent,
        Case,
        Evidence,
        EvidenceChunk,
        Person,
        PersonLink,
    )

    engine = get_engine()
    _migrate_columns(engine)
    SQLModel.metadata.create_all(engine)
    _init_fts(engine)


def get_session():
    with Session(get_engine()) as session:
        yield session