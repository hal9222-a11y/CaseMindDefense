import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_report_for_case_contains_custody_chain(tmp_path):
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"תיק דוח {uuid.uuid4().hex[:6]}"}).json()

        marker = uuid.uuid4().hex
        p = tmp_path / f"stmt_{marker}.txt"
        p.write_text(f"העד ראה את האירוע בתאריך 2024-03-05. {marker}", encoding="utf-8")
        ev = client.post(
            "/evidence/import-file", json={"path": str(p), "case_id": case["id"]}
        ).json()

        r = client.post("/reports", json={"case_id": case["id"]})
        assert r.status_code == 200
        result = r.json()
        assert result["evidence_count"] == 1

        report = Path(result["path"])
        assert report.exists()
        html = report.read_text(encoding="utf-8")
        assert p.name in html                    # evidence listed
        assert ev["sha256"] in html              # custody chain hash
        assert "2024-03-05" in html              # timeline event
        assert case["name"] in html
        assert 'dir="rtl"' in html


def test_report_all_cases_smoke():
    with TestClient(app) as client:
        r = client.post("/reports", json={})
        assert r.status_code == 200
        assert Path(r.json()["path"]).exists()
