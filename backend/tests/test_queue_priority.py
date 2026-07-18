"""The resume queue must work fast/high-value material first: text & chats,
then images, then audio, then video — not blind id order (which would bury the
WhatsApp chats behind hundreds of hours of interrogation video)."""
import uuid

from sqlmodel import Session, select

from app.db import get_engine, init_db
from app.models.evidence import Evidence
from app.services.evidence_service import _processing_priority


def _mk(session, case_id, name, size_bytes=1):
    ev = Evidence(
        case_id=case_id, original_path=f"x/{name}", stored_path=f"x/{name}",
        filename=name, sha256=uuid.uuid4().hex, size_bytes=size_bytes,
        mime_type="application/octet-stream", status="processing",
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev.id


def test_priority_orders_text_audio_images_video():
    init_db()
    with Session(get_engine()) as s:
        case = uuid.uuid4().int % 1_000_000
        # insert in an order that id-sorting would get WRONG
        vid = _mk(s, case, "interrogation.vob")
        img = _mk(s, case, "photo.jpg")
        aud = _mk(s, case, "voice.opus")
        txt = _mk(s, case, "whatsapp_chat.ufdr")
        ids = {vid, aud, img, txt}

        ordered = s.exec(
            select(Evidence.id)
            .where(Evidence.id.in_(ids))
            .order_by(*_processing_priority())
        ).all()
    # text/ufdr first, then AUDIO (voice notes/calls are the key evidence),
    # then images, video last — regardless of insertion (id) order
    assert ordered[0] == txt
    assert ordered[1] == aud
    assert ordered[2] == img
    assert ordered[3] == vid


def test_within_a_tier_shortest_first():
    # 99% of a dump's audio is short voice notes; the few long call recordings
    # each take hours, so short-first drains the quick wins before the queue
    # spends hours per long call. Size proxies duration.
    init_db()
    with Session(get_engine()) as s:
        case = uuid.uuid4().int % 1_000_000
        long_call = _mk(s, case, "call_60min.wav", size_bytes=60_000_000)  # inserted first
        short_note = _mk(s, case, "note.opus", size_bytes=20_000)
        ordered = s.exec(
            select(Evidence.id)
            .where(Evidence.id.in_({long_call, short_note}))
            .order_by(*_processing_priority())
        ).all()
    assert ordered == [short_note, long_call]  # smallest first despite older id
