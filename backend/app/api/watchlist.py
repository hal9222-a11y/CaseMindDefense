from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select, func

from app.db import get_session
from app.models.evidence import Evidence, WatchlistHit, WatchlistItem
from app.services.audit_service import log_event
from app.services.watchlist_service import backfill_item, detect_kind

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistCreate(BaseModel):
    term: str
    case_id: int | None = None


@router.get("")
def list_items(case_id: int | None = Query(None), session: Session = Depends(get_session)):
    query = select(WatchlistItem)
    if case_id is not None:
        query = query.where((WatchlistItem.case_id == case_id) | (WatchlistItem.case_id.is_(None)))
    items = session.exec(query.order_by(WatchlistItem.created_at.desc())).all()
    counts = dict(
        session.exec(
            select(WatchlistHit.watchlist_item_id, func.count()).group_by(WatchlistHit.watchlist_item_id)
        ).all()
    )
    unseen = dict(
        session.exec(
            select(WatchlistHit.watchlist_item_id, func.count())
            .where(WatchlistHit.seen == False)  # noqa: E712
            .group_by(WatchlistHit.watchlist_item_id)
        ).all()
    )
    return [
        {
            "id": i.id,
            "term": i.term,
            "kind": i.kind,
            "case_id": i.case_id,
            "hits": counts.get(i.id, 0),
            "unseen": unseen.get(i.id, 0),
        }
        for i in items
    ]


@router.post("")
def add_item(req: WatchlistCreate, session: Session = Depends(get_session)):
    term = req.term.strip()
    if len(term) < 2:
        raise HTTPException(status_code=400, detail="term too short")
    dup = session.exec(
        select(WatchlistItem).where(WatchlistItem.term == term, WatchlistItem.case_id == req.case_id)
    ).first()
    if dup:
        raise HTTPException(status_code=409, detail="term already on the watchlist")

    item = WatchlistItem(term=term, case_id=req.case_id, kind=detect_kind(term))
    session.add(item)
    session.commit()
    session.refresh(item)
    backfilled = backfill_item(session, item)
    log_event(session, "watchlist_term_added", detail=f"term={term!r} kind={item.kind} backfilled={backfilled}")
    return {"id": item.id, "term": item.term, "kind": item.kind, "case_id": item.case_id, "hits": backfilled}


@router.delete("/{item_id}")
def delete_item(item_id: int, session: Session = Depends(get_session)):
    item = session.get(WatchlistItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    for hit in session.exec(select(WatchlistHit).where(WatchlistHit.watchlist_item_id == item_id)).all():
        session.delete(hit)
    session.delete(item)
    session.commit()
    log_event(session, "watchlist_term_removed", detail=f"term={item.term!r}")
    return {"ok": True}


@router.get("/hits")
def list_hits(
    case_id: int | None = Query(None),
    unseen_only: bool = Query(False),
    limit: int = Query(100, le=500),
    session: Session = Depends(get_session),
):
    query = (
        select(WatchlistHit, WatchlistItem.term, Evidence.filename)
        .join(WatchlistItem, WatchlistItem.id == WatchlistHit.watchlist_item_id)
        .join(Evidence, Evidence.id == WatchlistHit.evidence_id)
    )
    if case_id is not None:
        query = query.where((WatchlistItem.case_id == case_id) | (WatchlistItem.case_id.is_(None)))
    if unseen_only:
        query = query.where(WatchlistHit.seen == False)  # noqa: E712
    rows = session.exec(query.order_by(WatchlistHit.created_at.desc()).limit(limit)).all()
    return [
        {
            "id": h.id,
            "term": term,
            "evidence_id": h.evidence_id,
            "evidence_filename": filename,
            "chunk_index": h.chunk_index,
            "snippet": h.snippet,
            "seen": h.seen,
            "created_at": h.created_at.isoformat(),
        }
        for h, term, filename in rows
    ]


@router.post("/hits/{hit_id}/seen")
def mark_seen(hit_id: int, session: Session = Depends(get_session)):
    hit = session.get(WatchlistHit, hit_id)
    if hit is None:
        raise HTTPException(status_code=404, detail="not found")
    hit.seen = True
    session.add(hit)
    session.commit()
    return {"ok": True}


@router.post("/hits/seen-all")
def mark_all_seen(case_id: int | None = Query(None), session: Session = Depends(get_session)):
    query = select(WatchlistHit).where(WatchlistHit.seen == False)  # noqa: E712
    if case_id is not None:
        query = query.join(WatchlistItem, WatchlistItem.id == WatchlistHit.watchlist_item_id).where(
            (WatchlistItem.case_id == case_id) | (WatchlistItem.case_id.is_(None))
        )
    count = 0
    for hit in session.exec(query).all():
        hit.seen = True
        session.add(hit)
        count += 1
    session.commit()
    return {"marked": count}
