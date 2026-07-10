import logging

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk

logger = logging.getLogger(__name__)


def _row_dict(chunk: EvidenceChunk, evidence: Evidence | None) -> dict:
    return {
        "evidence_id": chunk.evidence_id,
        "filename": evidence.filename if evidence else None,
        "chunk_index": chunk.chunk_index,
        "source_location": chunk.source_location,
        "score": 1.0,
        "text": chunk.text,
    }


def _fts_search(session: Session, query: str, limit: int) -> list[dict]:
    # phrase match; escape embedded double quotes per FTS5 syntax
    phrase = '"' + query.replace('"', '""') + '"'
    rows = session.connection().exec_driver_sql(
        "SELECT c.id FROM chunk_fts f JOIN evidencechunk c ON c.id = f.rowid "
        "WHERE chunk_fts MATCH ? ORDER BY rank LIMIT ?",
        (phrase, limit),
    ).fetchall()
    results = []
    for (chunk_id,) in rows:
        chunk = session.get(EvidenceChunk, chunk_id)
        if chunk is None:
            continue
        evidence = session.get(Evidence, chunk.evidence_id)
        results.append(_row_dict(chunk, evidence))
    return results


def _like_search(session: Session, query: str, limit: int) -> list[dict]:
    rows = session.exec(
        select(EvidenceChunk, Evidence)
        .join(Evidence, Evidence.id == EvidenceChunk.evidence_id)
        .where(EvidenceChunk.text.contains(query))  # type: ignore[attr-defined]
        .limit(limit)
    ).all()
    return [_row_dict(chunk, evidence) for chunk, evidence in rows]


def search_chunks(session: Session, q: str, limit: int = 10) -> list[dict]:
    query = (q or "").strip()
    if not query:
        return []
    try:
        return _fts_search(session, query, limit)
    except Exception as exc:
        # no FTS5 in this SQLite build (or table missing) - LIKE still works
        logger.debug("FTS search unavailable, falling back to LIKE: %s", exc)
        return _like_search(session, query, limit)
