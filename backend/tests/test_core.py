from fastapi.testclient import TestClient
from app.main import app
from app.services.hash_service import sha256_file
from app.services.text_service import chunk_text

def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_chunk_text():
    assert len(chunk_text("a" * 2000, chunk_size=500, overlap=50)) > 1

def test_sha256_file(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")
    assert len(sha256_file(p)) == 64

def test_import_and_audit(tmp_path):
    with TestClient(app) as client:
        p = tmp_path / "report.txt"
        p.write_text("The witness saw a white vehicle near the house.", encoding="utf-8")
        r = client.post("/evidence/import-file", json={"path": str(p)})
        assert r.status_code == 200
        assert r.json()["status"] == "processing"
        # TestClient runs background tasks before returning, so the follow-up
        # GET sees the final status
        final = client.get(f"/evidence/{r.json()['id']}")
        assert final.status_code == 200
        assert final.json()["status"] == "indexed"
        assert client.get("/audit").status_code == 200

def test_duplicate_import(tmp_path):
    with TestClient(app) as client:
        p = tmp_path / "dup.txt"
        p.write_text("duplicate", encoding="utf-8")
        assert client.post("/evidence/import-file", json={"path": str(p)}).status_code == 200
        assert client.post("/evidence/import-file", json={"path": str(p)}).status_code == 409

def test_import_missing_file():
    with TestClient(app) as client:
        assert client.post("/evidence/import-file", json={"path": "Z:/missing/file.txt"}).status_code == 404

def test_search_after_import(tmp_path):
    with TestClient(app) as client:
        p = tmp_path / "search.txt"
        p.write_text("alpha beta gamma", encoding="utf-8")
        client.post("/evidence/import-file", json={"path": str(p)})
        r = client.get("/search", params={"q": "beta", "limit": 5})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

def test_entities_timeline_contradictions_endpoints():
    with TestClient(app) as client:
        assert client.get("/entities").status_code == 200
        assert client.get("/timeline").status_code == 200
        assert client.get("/contradictions").status_code == 200
