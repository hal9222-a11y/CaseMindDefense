import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import get_engine
from app.main import app
from app.services import contradiction_service, llm_service
from app.services.contradiction_service import find_contradictions


def _import_pair(client, tmp_path, marker):
    """Import a contradicting witness pair into a fresh case; return case_id.
    Scoping find_contradictions to this case isolates the test from any other
    evidence in the shared DB (the pre-existing flake)."""
    case_id = client.post("/cases", json={"name": f"Contra {marker}"}).json()["id"]
    a = tmp_path / f"witness_a_{marker}.txt"
    a.write_text(f"העד ראה רכב לבן ליד הבית בשעה שמונה בערב {marker}", encoding="utf-8")
    b = tmp_path / f"witness_b_{marker}.txt"
    b.write_text(f"העד ראה רכב שחור ליד הבית בשעה שמונה בערב {marker}", encoding="utf-8")
    for p in (a, b):
        r = client.post("/evidence/import-file", json={"path": str(p), "case_id": case_id})
        assert r.status_code == 200
    return case_id


def test_contradiction_detected_with_llm_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    monkeypatch.setattr(
        llm_service,
        "judge_contradiction",
        lambda a, b: {"verdict": "contradiction", "explanation": "צבע הרכב שונה"},
    )
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        case_id = _import_pair(client, tmp_path, marker)

    with Session(get_engine()) as session:
        # low threshold so the hash-fallback embeddings used in CI also pair
        results = find_contradictions(session, sim_threshold=0.3, max_llm_pairs=5, case_id=case_id)

    ours = [r for r in results if marker in (r["text_a"] + r["text_b"])]
    assert ours, f"no contradiction found among {len(results)} results"
    assert ours[0]["verdict"] == "contradiction"
    assert ours[0]["explanation"] == "צבע הרכב שונה"
    assert ours[0]["evidence_a"] != ours[0]["evidence_b"]


def test_consistent_pairs_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    monkeypatch.setattr(
        llm_service, "judge_contradiction",
        lambda a, b: {"verdict": "consistent", "explanation": ""},
    )
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        case_id = _import_pair(client, tmp_path, marker)

    with Session(get_engine()) as session:
        results = find_contradictions(session, sim_threshold=0.3, max_llm_pairs=5, case_id=case_id)
    assert not [r for r in results if marker in (r["text_a"] + r["text_b"])]


def test_no_llm_returns_unverified_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: False)
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        case_id = _import_pair(client, tmp_path, marker)

    with Session(get_engine()) as session:
        results = find_contradictions(session, sim_threshold=0.3, max_llm_pairs=5, case_id=case_id)
    ours = [r for r in results if marker in (r["text_a"] + r["text_b"])]
    assert ours and ours[0]["verdict"] == "unverified"


def test_contradictions_endpoint_smoke():
    with TestClient(app) as client:
        r = client.get("/contradictions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
