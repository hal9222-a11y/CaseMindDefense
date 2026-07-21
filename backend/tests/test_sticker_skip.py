"""A <30KB image or any .webp is a WhatsApp sticker/thumbnail/emoji — never
evidentiary text. index_evidence must skip OCR on those (a phone dump has ~15k)
and land them in no_text_found, while still OCR'ing a real (larger) photo."""
import uuid

from sqlmodel import Session

from app.db import get_engine, init_db
from app.models.evidence import Evidence
from app.services import evidence_service


def _mk(session, filename, size_bytes):
    ev = Evidence(
        original_path=filename, stored_path=filename, filename=filename,
        sha256=uuid.uuid4().hex, size_bytes=size_bytes, mime_type="image/x",
        status="processing",
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev.id


def test_sticker_images_skip_ocr(monkeypatch):
    init_db()
    with Session(get_engine()) as s:
        tiny_jpg = _mk(s, "thumb.jpg", 8000)     # <30KB -> sticker
        webp = _mk(s, "sticker.webp", 200000)     # any .webp -> sticker (size ignored)
        real_photo = _mk(s, "photo.jpg", 900000)  # a real photo -> must OCR

    calls: list[str] = []

    def fake_extract(path):
        calls.append(str(path))
        return "", "ocr"  # real OCR path, found no text here

    monkeypatch.setattr(evidence_service, "extract_text", fake_extract)

    with Session(get_engine()) as s:
        for eid in (tiny_jpg, webp, real_photo):
            evidence_service.index_evidence(s, eid)
        assert s.get(Evidence, tiny_jpg).status == "no_text_found"
        assert s.get(Evidence, webp).status == "no_text_found"
        assert s.get(Evidence, real_photo).status == "no_text_found"

    # OCR ran ONLY for the real photo — the two stickers never reached extract_text
    assert len(calls) == 1 and "photo.jpg" in calls[0]
