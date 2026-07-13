import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import evidence_ai_service, llm_service
from app.services.llm_service import _clean_answer, _has_prose


def test_clean_answer_normalizes_small_model_artifacts():
    # small models sometimes render the Hebrew definite article as "_the"
    raw = "_theנאשם מכחיש את האישום. [_1] [2] [5] [12]"
    cleaned = _clean_answer(raw, 3)
    assert cleaned.startswith("נאשם")
    assert "[1]" in cleaned and "[2]" in cleaned
    assert "[5]" not in cleaned and "[12]" not in cleaned


def test_clean_answer_splits_grouped_citations_and_drops_hallucinated():
    # aya-style grouped markers with out-of-range indices
    raw = "הנאשם מכחיש את כל האישומים [1,2,3,4]. פירוט נוסף [2,5,6]."
    cleaned = _clean_answer(raw, 4)
    assert "[1][2][3][4]" in cleaned
    assert "[2]" in cleaned.split(".")[1]
    assert "[5]" not in cleaned and "[6]" not in cleaned


def test_has_prose_rejects_citation_only_answers():
    # a small model that emits only markers is not a real answer
    assert _has_prose("[3]") is False
    assert _has_prose(" [1] , [2]. ") is False
    assert _has_prose("") is False
    assert _has_prose("הנאשם מכחיש [2].") is True
    assert _has_prose("The suspect denies it [1].") is True


def test_ask_falls_back_when_llm_returns_only_citations(tmp_path, monkeypatch):
    # regression: model answered "[3]" with no prose — user must still see the
    # evidence text, so synthesize_answer signals failure -> citations_only
    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    monkeypatch.setattr(llm_service, "_chat", lambda messages: "[3]")
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        _import_marked_doc(client, tmp_path, marker)
        r = client.post("/ai/ask", json={"question": f"white vehicle {marker}"})
        data = r.json()
        assert data["mode"] == "citations_only"
        assert len(data["citations"]) >= 1


def _import_marked_doc(client, tmp_path, marker):
    p = tmp_path / f"stmt_{marker}.txt"
    p.write_text(f"The witness described a white vehicle. Marker {marker}.", encoding="utf-8")
    r = client.post("/evidence/import-file", json={"path": str(p)})
    assert r.status_code == 200
    return r.json()["id"]


def test_ask_falls_back_to_citations_when_llm_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: False)
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        _import_marked_doc(client, tmp_path, marker)
        r = client.post("/ai/ask", json={"question": f"white vehicle {marker}"})
        assert r.status_code == 200
        data = r.json()
        assert data["mode"] == "citations_only"
        assert len(data["citations"]) >= 1


def test_ask_uses_llm_answer_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    monkeypatch.setattr(
        llm_service, "synthesize_answer",
        lambda question, citations: "The witness saw a white vehicle [1].",
    )
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        _import_marked_doc(client, tmp_path, marker)
        r = client.post("/ai/ask", json={"question": f"white vehicle {marker}"})
        data = r.json()
        assert data["mode"] == "llm"
        assert "[1]" in data["answer"]
        assert len(data["citations"]) >= 1


def test_llm_not_found_keeps_citations_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    monkeypatch.setattr(llm_service, "synthesize_answer", lambda q, c: "NOT_FOUND")
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        _import_marked_doc(client, tmp_path, marker)
        r = client.post("/ai/ask", json={"question": f"white vehicle {marker}"})
        data = r.json()
        assert data["answer"] == evidence_ai_service.NOT_FOUND_ANSWER
        assert len(data["citations"]) >= 1


def test_llm_failure_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    monkeypatch.setattr(llm_service, "synthesize_answer", lambda q, c: None)
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        _import_marked_doc(client, tmp_path, marker)
        r = client.post("/ai/ask", json={"question": f"white vehicle {marker}"})
        assert r.json()["mode"] == "citations_only"
