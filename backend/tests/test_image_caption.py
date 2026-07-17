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
