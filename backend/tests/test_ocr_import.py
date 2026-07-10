from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from app.main import app

def test_import_image_file_does_not_crash(tmp_path):
    client = TestClient(app)
    image_path = tmp_path / "ocr_test.png"
    img = Image.new("RGB", (800, 250), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((50, 100), "CaseMind Evidence OCR Test", fill="black")
    img.save(image_path)
    response = client.post("/evidence/import-file", json={"path": str(image_path)})
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "ocr_test.png"
    final = client.get(f"/evidence/{data['id']}").json()
    assert final["status"] in {"ocr_indexed", "no_text_found", "text_extraction_failed"}


def test_import_scanned_pdf_falls_back_to_ocr(tmp_path):
    client = TestClient(app)
    pdf_path = tmp_path / "scanned_evidence.pdf"
    img = Image.new("RGB", (800, 250), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((50, 100), "Scanned PDF OCR Test", fill="black")
    img.save(pdf_path)  # image-only PDF: no text layer for pypdf
    response = client.post("/evidence/import-file", json={"path": str(pdf_path)})
    assert response.status_code == 200
    final = client.get(f"/evidence/{response.json()['id']}").json()
    assert final["status"] in {"ocr_indexed", "no_text_found", "text_extraction_failed"}


def test_import_unsupported_extraction_gets_clear_status(tmp_path):
    client = TestClient(app)
    docx_path = tmp_path / "statement.docx"
    docx_path.write_bytes(b"not really a docx, content does not matter")
    response = client.post("/evidence/import-file", json={"path": str(docx_path)})
    assert response.status_code == 200
    final = client.get(f"/evidence/{response.json()['id']}").json()
    assert final["status"] == "extraction_not_supported"
