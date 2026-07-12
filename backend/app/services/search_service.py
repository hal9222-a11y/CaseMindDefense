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


def _fts_search(session: Session, query: str, limit: int, case_id: int | None) -> list[dict]:
    # phrase match; escape embedded double quotes per FTS5 syntax
    phrase = '"' + query.replace('"', '""') + '"'
    sql = (
        "SELECT c.id FROM chunk_fts f JOIN evidencechunk c ON c.id = f.rowid "
        "WHERE chunk_fts MATCH ?"
    )
    params: list = [phrase]
    if case_id is not None:
        sql += " AND c.evidence_id IN (SELECT id FROM evidence WHERE case_id = ?)"
        params.append(case_id)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    rows = session.connection().exec_driver_sql(sql, tuple(params)).fetchall()
    results = []
    for (chunk_id,) in rows:
        chunk = session.get(EvidenceChunk, chunk_id)
        if chunk is None:
            continue
        evidence = session.get(Evidence, chunk.evidence_id)
        results.append(_row_dict(chunk, evidence))
    return results


def _like_search(session: Session, query: str, limit: int, case_id: int | None) -> list[dict]:
    stmt = (
        select(EvidenceChunk, Evidence)
        .join(Evidence, Evidence.id == EvidenceChunk.evidence_id)
        .where(EvidenceChunk.text.contains(query))  # type: ignore[attr-defined]
    )
    if case_id is not None:
        stmt = stmt.where(Evidence.case_id == case_id)
    rows = session.exec(stmt.limit(limit)).all()
    return [_row_dict(chunk, evidence) for chunk, evidence in rows]


def search_chunks(session: Session, q: str, limit: int = 10, case_id: int | None = None) -> list[dict]:
    query = (q or "").strip()
    if not query:
        return []
    try:
        return _fts_search(session, query, limit, case_id)
    except Exception as exc:
        # no FTS5 in this SQLite build (or table missing) - LIKE still works
        logger.debug("FTS search unavailable, falling back to LIKE: %s", exc)
        return _like_search(session, query, limit, case_id)
