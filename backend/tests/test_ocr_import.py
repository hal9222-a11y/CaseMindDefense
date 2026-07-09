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
    assert data["status"] in {"indexed", "no_text_found", "text_extraction_failed"}
