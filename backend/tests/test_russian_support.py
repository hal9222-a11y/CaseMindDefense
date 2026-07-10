import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import ner_service
from app.services.text_service import OCR_LANGS


def test_cyrillic_entities_extracted(tmp_path, monkeypatch):
    monkeypatch.setattr(ner_service, "_load_ner", lambda: None)
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        p = tmp_path / f"rus_{marker}.txt"
        p.write_text(
            f"Свидетель Владимир Петров видел белый автомобиль возле дома. {marker}",
            encoding="utf-8",
        )
        assert client.post("/evidence/import-file", json={"path": str(p)}).status_code == 200

        entities = client.get("/entities", params={"limit": 500}).json()
        names = {e["entity"] for e in entities if e["type"] == "name"}
        assert "Владимир" in names
        assert "Петров" in names


def test_ocr_langs_never_requests_missing_pack():
    # OCR_LANGS is computed from installed packs; every requested language
    # must actually exist, otherwise all OCR calls fail
    import pytesseract

    installed = set(pytesseract.get_languages(config=""))
    for lang in OCR_LANGS.split("+"):
        assert lang in installed, f"{lang} requested but not installed"


def test_russian_keyword_search(tmp_path):
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        p = tmp_path / f"rus_kw_{marker}.txt"
        p.write_text(f"Обвиняемый отрицает все обвинения. {marker}", encoding="utf-8")
        assert client.post("/evidence/import-file", json={"path": str(p)}).status_code == 200

        results = client.get("/search", params={"q": marker, "limit": 5}).json()
        assert len(results) == 1
        assert "отрицает" in results[0]["text"]
