import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_delete_case_removes_case_and_all_its_evidence(tmp_path):
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        case_id = client.post("/cases", json={"name": f"Closed matter {marker}"}).json()["id"]

        stored_paths = []
        for i in range(2):
            p = tmp_path / f"doc_{i}_{marker}.txt"
            p.write_text(f"evidence {i} for {marker}", encoding="utf-8")
            ev = client.post(
                "/evidence/import-file", json={"path": str(p), "case_id": case_id}
            ).json()
            stored_paths.append(ev["stored_path"])

        # sanity: the case has evidence and it is searchable
        assert len(client.get("/evidence", params={"case_id": case_id}).json()) == 2
        assert len(client.get("/search", params={"q": marker}).json()) == 2

        r = client.delete(f"/cases/{case_id}")
        assert r.status_code == 200
        assert r.json()["evidence_deleted"] == 2

        # case gone, its evidence gone, nothing left in search, files removed
        assert case_id not in {c["id"] for c in client.get("/cases").json()}
        assert client.get("/evidence", params={"case_id": case_id}).json() == []
        assert client.get("/search", params={"q": marker}).json() == []
        for sp in stored_paths:
            assert not Path(sp).exists()


def test_delete_missing_case_404():
    with TestClient(app) as client:
        assert client.delete("/cases/999999").status_code == 404


def test_delete_case_leaves_other_cases_untouched(tmp_path):
    with TestClient(app) as client:
        m = uuid.uuid4().hex
        keep = client.post("/cases", json={"name": f"Keep {m}"}).json()["id"]
        drop = client.post("/cases", json={"name": f"Drop {m}"}).json()["id"]

        pk = tmp_path / f"keep_{m}.txt"
        pk.write_text(f"keep this {m}", encoding="utf-8")
        ev_keep = client.post(
            "/evidence/import-file", json={"path": str(pk), "case_id": keep}
        ).json()["id"]
        pd = tmp_path / f"drop_{m}.txt"
        pd.write_text(f"drop this {m}", encoding="utf-8")
        client.post("/evidence/import-file", json={"path": str(pd), "case_id": drop})

        client.delete(f"/cases/{drop}")

        assert keep in {c["id"] for c in client.get("/cases").json()}
        assert client.get(f"/evidence/{ev_keep}").status_code == 200

        client.delete(f"/evidence/{ev_keep}")  # cleanup
        client.delete(f"/cases/{keep}")
