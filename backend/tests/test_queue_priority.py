"""The resume queue must work fast/high-value material first: text & chats,
then images, then audio, then video — not blind id order (which would bury the
WhatsApp chats behind hundreds of hours of interrogation video)."""
import uuid

from sqlmodel import Session, select

from app.db import get_engine, init_db
from app.models.evidence import Evidence
from app.services.evidence_service import _processing_priority


def _mk(session, case_id, name):
    ev = Evidence(
        case_id=case_id, original_path=f"x/{name}", stored_path=f"x/{name}",
        filename=name, sha256=uuid.uuid4().hex, size_bytes=1,
        mime_type="application/octet-stream", status="processing",
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev.id


def test_priority_orders_text_images_audio_video():
    init_db()
    with Session(get_engine()) as s:
        case = uuid.uuid4().int % 1_000_000
        # insert in an order that id-sorting would get WRONG
        vid = _mk(s, case, "interrogation.vob")
        aud = _mk(s, case, "voice.opus")
        img = _mk(s, case, "photo.jpg")
        txt = _mk(s, case, "whatsapp_chat.ufdr")
        ids = {vid, aud, img, txt}

        ordered = s.exec(
            select(Evidence.id)
            .where(Evidence.id.in_(ids))
            .order_by(*_processing_priority())
        ).all()
    # text/ufdr first, video last, regardless of insertion (id) order
    assert ordered[0] == txt
    assert ordered[1] == img
    assert ordered[2] == aud
    assert ordered[3] == vid
