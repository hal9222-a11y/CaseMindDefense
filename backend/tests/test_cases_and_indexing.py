import uuid

from fastapi.testclient import TestClient

from app.main import app


def test_create_case_and_import_into_it(tmp_path):
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"State vs. Test {uuid.uuid4().hex[:8]}"})
        assert case.status_code == 200
        case_id = case.json()["id"]

        p = tmp_path / f"case_doc_{uuid.uuid4().hex}.txt"
        p.write_text("evidence inside a specific case", encoding="utf-8")
        r = client.post("/evidence/import-file", json={"path": str(p), "case_id": case_id})
        assert r.status_code == 200
        assert r.json()["case_id"] == case_id

        in_case = client.get("/evidence", params={"case_id": case_id}).json()
        assert len(in_case) == 1
        assert in_case[0]["case_id"] == case_id

        other_case = client.get("/evidence", params={"case_id": case_id + 999}).json()
        assert other_case == []


def test_blank_case_name_rejected():
    with TestClient(app) as client:
        assert client.post("/cases", json={"name": "   "}).status_code == 422


def test_reindex_rebuilds_chunks(tmp_path):
    with TestClient(app) as client:
        p = tmp_path / f"reindex_{uuid.uuid4().hex}.txt"
        p.write_text("reindex me please", encoding="utf-8")
        ev = client.post("/evidence/import-file", json={"path": str(p)}).json()

        r = client.post(f"/evidence/{ev['id']}/reindex")
        assert r.status_code == 200
        final = client.get(f"/evidence/{ev['id']}").json()
        assert final["status"] == "indexed"


def test_delete_evidence_removes_everything(tmp_path):
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        p = tmp_path / f"todelete_{marker}.txt"
        p.write_text(f"delete me {marker}", encoding="utf-8")
        ev = client.post("/evidence/import-file", json={"path": str(p)}).json()

        assert client.delete(f"/evidence/{ev['id']}").status_code == 200
        assert client.get(f"/evidence/{ev['id']}").status_code == 404
        results = client.get("/search", params={"q": marker, "limit": 5}).json()
        assert results == []
        # re-import works (hash no longer registered)
        assert client.post("/evidence/import-file", json={"path": str(p)}).status_code == 200


def test_import_folder_registers_and_indexes(tmp_path):
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        for i in range(3):
            (tmp_path / f"doc_{i}_{marker}.txt").write_text(
                f"folder doc {i} {marker}", encoding="utf-8"
            )
        r = client.post("/evidence/import-folder", json={"path": str(tmp_path)})
        assert r.status_code == 200
        body = r.json()
        assert body["registered"] == 3
        assert body["errors"] == []

        results = client.get("/search", params={"q": marker, "limit": 10}).json()
        assert len(results) == 3
