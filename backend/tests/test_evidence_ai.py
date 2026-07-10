from fastapi.testclient import TestClient
from app.main import app

def test_evidence_ai_answer_returns_citations(tmp_path):
    client = TestClient(app)
    evidence_file = tmp_path / "witness_statement.txt"
    evidence_file.write_text("The witness stated that a white vehicle was parked near the house.", encoding="utf-8")
    import_response = client.post("/evidence/import-file", json={"path": str(evidence_file)})
    assert import_response.status_code == 200
    final = client.get(f"/evidence/{import_response.json()['id']}").json()
    assert final["status"] == "indexed"
    ai_response = client.post("/ai/ask", json={"question": "What evidence mentions a white vehicle?"})
    assert ai_response.status_code == 200
    data = ai_response.json()
    assert "answer" in data
    assert "citations" in data
    assert len(data["citations"]) >= 1
    assert any(citation["filename"] == "witness_statement.txt" and "white vehicle" in citation["text"] for citation in data["citations"])
