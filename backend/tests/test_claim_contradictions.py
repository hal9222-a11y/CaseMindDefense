"""Claim-level contradiction engine: decomposes statements, cross-compares,
classifies, and verifies each hit with a second judge pass. The LLM is stubbed
so the test is deterministic and offline."""
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import llm_service, claim_contradiction_service


def _case(client):
    return client.post("/cases", json={"name": f"claim_{uuid.uuid4().hex[:8]}"}).json()


def _import_text(client, case_id, text):
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.write(fd, text.encode("utf-8"))
    os.close(fd)
    client.post("/evidence/import-file", json={"path": path, "case_id": case_id})


def test_claim_contradiction_screens_and_verifies(monkeypatch):
    # LLM screening: one contradiction pair across the two sources
    def fake_analyze(sources, role=""):
        assert len(sources) >= 2  # both statements reached the model
        return [{
            "claim_a": "לא הכרתי אותו מעולם",
            "claim_b": "43 שיחות בחודש הקודם",
            "source_a": 0, "source_b": 1,
            "type": "contradiction", "severity": "high",
            "explanation": "הכחשת היכרות מול תיעוד שיחות",
        }]

    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    monkeypatch.setattr(llm_service, "analyze_claim_contradictions", fake_analyze)
    # second-model verification confirms it
    monkeypatch.setattr(llm_service, "judge_contradiction",
                        lambda a, b: {"verdict": "contradiction", "explanation": "x"})

    with TestClient(app) as client:
        case = _case(client)
        _import_text(client, case["id"], "בחקירה: לא הכרתי אותו מעולם, לא דיברנו אף פעם.")
        _import_text(client, case["id"], "פלט תקשורת: 43 שיחות בין המספרים בחודש הקודם.")

        r = client.get(f"/contradictions/claims?case_id={case['id']}").json()
        assert r["status"] == "ok"
        assert len(r["contradictions"]) == 1
        hit = r["contradictions"][0]
        assert hit["type"] == "contradiction" and hit["severity"] == "high"
        assert hit["verified"] is True
        assert hit["source_a"] and hit["source_b"] and hit["source_a"] != hit["source_b"]
        client.delete(f"/cases/{case['id']}")


def test_unverified_contradiction_is_marked(monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    # string indices ("0"/"1") — local models often return them; must still map
    monkeypatch.setattr(llm_service, "analyze_claim_contradictions",
                        lambda sources, role="": [{
                            "claim_a": "a", "claim_b": "b", "source_a": "0", "source_b": "1",
                            "type": "contradiction", "severity": "medium", "explanation": "",
                        }])
    # the judge disagrees -> verified False, still shown but not as confirmed
    monkeypatch.setattr(llm_service, "judge_contradiction",
                        lambda a, b: {"verdict": "consistent", "explanation": ""})

    with TestClient(app) as client:
        case = _case(client)
        _import_text(client, case["id"], "טקסט ראשון עם טענה כלשהי.")
        _import_text(client, case["id"], "טקסט שני עם טענה אחרת.")
        r = client.get(f"/contradictions/claims?case_id={case['id']}").json()
        hit = r["contradictions"][0]
        assert hit["verified"] is False
        assert hit["source_a"] and hit["source_b"]  # string indices mapped to sources
        client.delete(f"/cases/{case['id']}")


def test_needs_two_sources(monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    with TestClient(app) as client:
        case = _case(client)
        _import_text(client, case["id"], "רק מקור אחד קיים כאן.")
        r = client.get(f"/contradictions/claims?case_id={case['id']}").json()
        assert r["status"] == "not_enough_sources"
        client.delete(f"/cases/{case['id']}")
