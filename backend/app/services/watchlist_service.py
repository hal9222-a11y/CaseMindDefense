"""Standing queries over the evidence stream (Aleph-style cross-referencing).

A watchlist item is a name, phone number or keyword. Every evidence that
finishes indexing is scanned against the case's watchlist and hits are
recorded; adding a term also backfills against everything already indexed.
This is what makes weeks of background transcription useful as it lands:
the lawyer sees "key person X appeared in 7 new transcripts" instead of
re-running searches by hand.
"""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk, WatchlistHit, WatchlistItem

logger = logging.getLogger(__name__)

_SNIPPET_RADIUS = 60


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def detect_kind(term: str) -> str:
    """A term that is mostly digits is a phone number; match it digits-normalized."""
    return "phone" if len(_digits(term)) >= 6 and len(_digits(term)) >= len(term) - 4 else "text"


def _match_positions(item: WatchlistItem, text: str) -> list[int]:
    """Start offsets of matches of the item in text (at most a few per chunk)."""
    if item.kind == "phone":
        # normalize the text's digit runs: find the term's digits inside the
        # digit-stream of the text, then map back to a rough position
        needle = _digits(item.term)
        stream, positions = [], []
        for i, ch in enumerate(text):
            if ch.isdigit():
                stream.append(ch)
                positions.append(i)
        idx = "".join(stream).find(needle)
        return [positions[idx]] if idx >= 0 else []
    lowered, needle = text.lower(), item.term.lower()
    out, start = [], 0
    while (pos := lowered.find(needle, start)) >= 0 and len(out) < 5:
        out.append(pos)
        start = pos + len(needle)
    return out


def _snippet(text: str, pos: int) -> str:
    lo, hi = max(0, pos - _SNIPPET_RADIUS), min(len(text), pos + _SNIPPET_RADIUS)
    return ("…" if lo > 0 else "") + text[lo:hi].replace("\n", " ") + ("…" if hi < len(text) else "")


def _items_for_case(session: Session, case_id: int | None) -> list[WatchlistItem]:
    """Items of this case, plus global items (case_id is NULL) which match everything."""
    items = list(session.exec(select(WatchlistItem).where(WatchlistItem.case_id == case_id)).all())
    if case_id is not None:
        items += list(session.exec(select(WatchlistItem).where(WatchlistItem.case_id.is_(None))).all())
    return items


def _record_hit(session: Session, item: WatchlistItem, evidence_id: int, chunk_index: int, snippet: str) -> bool:
    exists = session.exec(
        select(WatchlistHit.id).where(
            WatchlistHit.watchlist_item_id == item.id,
            WatchlistHit.evidence_id == evidence_id,
            WatchlistHit.chunk_index == chunk_index,
        )
    ).first()
    if exists:
        return False
    session.add(WatchlistHit(watchlist_item_id=item.id, evidence_id=evidence_id, chunk_index=chunk_index, snippet=snippet))
    return True


def scan_evidence(session: Session, evidence_id: int) -> int:
    """Match one (freshly indexed) evidence against its case's watchlist.
    Called from index_evidence — must never raise into the indexing path."""
    evidence = session.get(Evidence, evidence_id)
    if evidence is None:
        return 0
    items = _items_for_case(session, evidence.case_id)
    if not items:
        return 0

    hits = 0
    chunks = session.exec(select(EvidenceChunk).where(EvidenceChunk.evidence_id == evidence_id)).all()
    for chunk in chunks:
        for item in items:
            for pos in _match_positions(item, chunk.text):
                if _record_hit(session, item, evidence_id, chunk.chunk_index, _snippet(chunk.text, pos)):
                    hits += 1
    if hits:
        session.commit()
        logger.info("watchlist: %d new hits in evidence %s", hits, evidence_id)
    return hits


def backfill_item(session: Session, item: WatchlistItem) -> int:
    """Scan everything already indexed for a newly added term."""
    query = select(EvidenceChunk, Evidence.case_id).join(Evidence, Evidence.id == EvidenceChunk.evidence_id)  # noqa: E501
    if item.case_id is not None:
        query = query.where(Evidence.case_id == item.case_id)

    hits = 0
    for chunk, _case in session.exec(query):
        for pos in _match_positions(item, chunk.text):
            if _record_hit(session, item, chunk.evidence_id, chunk.chunk_index, _snippet(chunk.text, pos)):
                hits += 1
    if hits:
        session.commit()
    return hits
