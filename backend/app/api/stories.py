from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select, func

from app.db import get_session
from app.models.evidence import Evidence, Story, StoryItem
from app.services.audit_service import log_event

router = APIRouter(prefix="/stories", tags=["stories"])

ITEM_KINDS = {"note", "evidence", "search"}


class StoryCreate(BaseModel):
    case_id: int
    title: str


class ItemCreate(BaseModel):
    kind: str = "note"
    content: str = ""
    evidence_id: int | None = None


class ItemUpdate(BaseModel):
    content: str | None = None
    position: int | None = None


def _get_story(session: Session, story_id: int) -> Story:
    story = session.get(Story, story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="story not found")
    return story


@router.get("")
def list_stories(case_id: int, session: Session = Depends(get_session)):
    stories = session.exec(
        select(Story).where(Story.case_id == case_id).order_by(Story.created_at.desc())
    ).all()
    counts = dict(
        session.exec(select(StoryItem.story_id, func.count()).group_by(StoryItem.story_id)).all()
    )
    return [
        {"id": s.id, "title": s.title, "items": counts.get(s.id, 0), "created_at": s.created_at.isoformat()}
        for s in stories
    ]


@router.post("")
def create_story(req: StoryCreate, session: Session = Depends(get_session)):
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    story = Story(case_id=req.case_id, title=title)
    session.add(story)
    session.commit()
    session.refresh(story)
    log_event(session, "story_created", case_id=req.case_id, detail=title)
    return {"id": story.id, "title": story.title}


@router.get("/{story_id}")
def get_story(story_id: int, session: Session = Depends(get_session)):
    story = _get_story(session, story_id)
    items = session.exec(
        select(StoryItem).where(StoryItem.story_id == story_id).order_by(StoryItem.position, StoryItem.id)
    ).all()
    evidence_ids = [i.evidence_id for i in items if i.evidence_id]
    filenames = {}
    if evidence_ids:
        filenames = dict(
            session.exec(select(Evidence.id, Evidence.filename).where(Evidence.id.in_(evidence_ids))).all()
        )
    return {
        "id": story.id,
        "title": story.title,
        "case_id": story.case_id,
        "items": [
            {
                "id": i.id,
                "kind": i.kind,
                "content": i.content,
                "evidence_id": i.evidence_id,
                "evidence_filename": filenames.get(i.evidence_id),
                "position": i.position,
            }
            for i in items
        ],
    }


@router.post("/{story_id}/items")
def add_item(story_id: int, req: ItemCreate, session: Session = Depends(get_session)):
    story = _get_story(session, story_id)
    if req.kind not in ITEM_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(ITEM_KINDS)}")
    if req.kind == "evidence":
        if not req.evidence_id or session.get(Evidence, req.evidence_id) is None:
            raise HTTPException(status_code=404, detail="evidence not found")
    next_pos = (
        session.exec(select(func.max(StoryItem.position)).where(StoryItem.story_id == story_id)).one()
        or 0
    ) + 1
    item = StoryItem(
        story_id=story.id, kind=req.kind, content=req.content, evidence_id=req.evidence_id, position=next_pos
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"id": item.id, "position": item.position}


@router.patch("/{story_id}/items/{item_id}")
def update_item(story_id: int, item_id: int, req: ItemUpdate, session: Session = Depends(get_session)):
    _get_story(session, story_id)
    item = session.get(StoryItem, item_id)
    if item is None or item.story_id != story_id:
        raise HTTPException(status_code=404, detail="item not found")
    if req.content is not None:
        item.content = req.content
    if req.position is not None:
        item.position = req.position
    session.add(item)
    session.commit()
    return {"ok": True}


@router.delete("/{story_id}/items/{item_id}")
def delete_item(story_id: int, item_id: int, session: Session = Depends(get_session)):
    _get_story(session, story_id)
    item = session.get(StoryItem, item_id)
    if item is None or item.story_id != story_id:
        raise HTTPException(status_code=404, detail="item not found")
    session.delete(item)
    session.commit()
    return {"ok": True}


@router.delete("/{story_id}")
def delete_story(story_id: int, session: Session = Depends(get_session)):
    story = _get_story(session, story_id)
    for item in session.exec(select(StoryItem).where(StoryItem.story_id == story_id)).all():
        session.delete(item)
    session.delete(story)
    session.commit()
    log_event(session, "story_deleted", case_id=story.case_id, detail=story.title)
    return {"ok": True}
