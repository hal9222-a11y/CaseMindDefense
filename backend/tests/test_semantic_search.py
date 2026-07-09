import uuid
from fastapi.testclient import TestClient
from app.main import app


def test_semantic_search_returns_results_after_import(tmp_path):
    client = TestClient(app)

    marker = uuid.uuid4().hex
    evidence_file = tmp_path / f"vehicle_report_{marker}.txt"
    evidence_file.write_text(
        f"The witness saw a white vehicle near the house. Unique marker: {marker}",
        encoding="utf-8",
    )

    import_response = client.post(
        "/evidence/import-file",
        json={"path": str(evidence_file)},
    )

    assert import_response.status_code == 200
    assert import_response.json()["status"] == "indexed"

    search_response = client.get(
        "/search/semantic",
        params={"q": f"white vehicle {marker}", "limit": 10},
    )

    assert search_response.status_code == 200

    results = search_response.json()

    assert isinstance(results, list)
    assert len(results) >= 1

    assert any(
        result["filename"] == f"vehicle_report_{marker}.txt"
        and result["score"] > 0
        and marker in result["text"]
        and result["source_location"].startswith("chars:")
        for result in results
    )