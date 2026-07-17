"""Image description for findability: a photo with no readable text used to land
in 'no_text_found' and vanish from search. Now a vision model describes it and
that description is indexed like any other text. OCR and the vision call are both
stubbed so the test needs neither tesseract nor a running Ollama."""
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import evidence_service, llm_service


def test_description_is_dormant_by_default():
    # no CASEMIND_VISION_MODEL -> feature off, never touches Ollama
    assert llm_service.VISION_MODEL is None
    assert llm_service.describe_image("anything.png") is None


def test_downscale_shrinks_big_skips_corrupt_passes_small(tmp_path):
    """The vision model's cost scales with pixel count, and a corrupt file must
    be skipped (not sent raw — it stalls Ollama for the whole timeout)."""
    from io import BytesIO

    from PIL import Image

    from app.services.llm_service import VISION_MAX_SIDE, _downscaled_image_bytes

    big = tmp_path / "big.png"
    Image.new("RGB", (VISION_MAX_SIDE * 3, VISION_MAX_SIDE * 2), "blue").save(big)
    out = _downscaled_image_bytes(big)
    assert out is not None
    assert max(Image.open(BytesIO(out)).size) <= VISION_MAX_SIDE  # shrunk

    small = tmp_path / "small.png"
    Image.new("RGB", (32, 32), "red").save(small)
    assert _downscaled_image_bytes(small) == small.read_bytes()  # untouched

    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"\x89PNG\r\n\x1a\n definitely not a real image")
    assert _downscaled_image_bytes(corrupt) is None  # skipped, not raw

    assert _downscaled_image_bytes(tmp_path / "does_not_exist.png") is None


def test_no_text_image_gets_described_and_indexed(tmp_path, monkeypatch):
    marker = uuid.uuid4().hex
    caption = f"רכב לבן חונה ליד בניין משרדים {marker}"
    called = {}

    # the image has no OCR text (stub avoids a tesseract dependency)…
    monkeypatch.setattr(evidence_service, "extract_text", lambda p: ("", "ocr"))

    # …so the vision model's description is what makes it findable
    def fake_describe(path):
        called["path"] = str(path)
        return caption

    monkeypatch.setattr(llm_service, "describe_image", fake_describe)

    with TestClient(app) as client:
        p = tmp_path / f"photo_{marker}.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n not-a-real-image, ocr is stubbed")
        ev = client.post("/evidence/import-file", json={"path": str(p)}).json()
        client.post(f"/evidence/{ev['id']}/reindex")  # force synchronous indexing

        final = client.get(f"/evidence/{ev['id']}").json()
        assert called.get("path"), "the image was not sent for description"
        # without the description this image would be 'no_text_found' and invisible
        assert final["status"] == "indexed"


def test_caption_never_creates_entities(tmp_path, monkeypatch):
    """A caption is a vision model's guess, and this small model hallucinates
    names. The description must stay searchable but must NEVER seed the entity
    graph — otherwise an invented 'person' becomes a party in the case."""
    from sqlmodel import Session, select

    from app.db import get_engine
    from app.models.evidence import ExtractedEntity

    marker = uuid.uuid4().hex
    # a name-shaped caption: if NER ran on it, it would extract a 'person'
    caption = f"דוד לוי עומד ליד רכב במגרש חניה {marker}"

    monkeypatch.setattr(evidence_service, "extract_text", lambda p: ("", "ocr"))
    monkeypatch.setattr(llm_service, "describe_image", lambda path: caption)

    with TestClient(app) as client:
        p = tmp_path / f"photo_{marker}.png"
        # unique bytes: evidence dedups on content hash, so identical bytes to
        # another test would 409 instead of importing
        p.write_bytes(b"\x89PNG\r\n\x1a\n ner-skip test " + marker.encode())
        ev = client.post("/evidence/import-file", json={"path": str(p)}).json()
        client.post(f"/evidence/{ev['id']}/reindex")

        assert client.get(f"/evidence/{ev['id']}").json()["status"] == "indexed"
        with Session(get_engine()) as s:
            entities = s.exec(
                select(ExtractedEntity).where(ExtractedEntity.evidence_id == ev["id"])
            ).all()
        assert entities == [], f"caption seeded entities: {[e.text for e in entities]}"
