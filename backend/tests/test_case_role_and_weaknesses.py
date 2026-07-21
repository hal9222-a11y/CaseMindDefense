"""The user's role in the case (e.g. defense counsel of a specific person) is
stored per case and injected into every AI prompt, and the defense-lens
weaknesses analysis runs over the case sample with that framing."""
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import llm_service


def _case(client):
    return client.post("/cases", json={"name": f"role_{uuid.uuid4().hex[:8]}"}).json()


def test_role_is_saved_and_returned():
    with TestClient(app) as client:
        case = _case(client)
        r = client.patch(f"/cases/{case['id']}", json={"role_context": "סנגור של אמיר גורי"})
        assert r.status_code == 200 and r.json()["role_context"] == "סנגור של אמיר גורי"
        # visible on the case list too
        listed = {c["id"]: c for c in client.get("/cases").json()}
        assert listed[case["id"]]["role_context"] == "סנגור של אמיר גורי"
        # clearing works
        assert client.patch(f"/cases/{case['id']}", json={"role_context": ""}).json()["role_context"] == ""
        client.delete(f"/cases/{case['id']}")


def test_patch_missing_case_404():
    with TestClient(app) as client:
        assert client.patch("/cases/999999", json={"role_context": "x"}).status_code == 404


def test_weaknesses_uses_sample_and_role(tmp_path, monkeypatch):
    captured = {}

    def fake_chat(messages):
        captured["system"] = messages[0]["content"]
        return "• סתירה בין העדויות לגבי השעה"

    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    monkeypatch.setattr(llm_service, "_chat", fake_chat)

    with TestClient(app) as client:
        case = _case(client)
        client.patch(f"/cases/{case['id']}", json={"role_context": "סנגור של אמיר גורי"})
        p = tmp_path / f"w_{uuid.uuid4().hex}.txt"
        p.write_text("העד אמר שהיה בבית בשעה 22:00, אך במקום אחר נטען 23:00.", encoding="utf-8")
        client.post("/evidence/import-file", json={"path": str(p), "case_id": case["id"]})

        r = client.get(f"/insights/weaknesses?case_id={case['id']}").json()
        assert r["weaknesses"] == "• סתירה בין העדויות לגבי השעה"
        assert "סנגור של אמיר גורי" in captured["system"]   # role framed the prompt
        assert "חולשות" in captured["system"]                # defense-lens prompt used
        client.delete(f"/cases/{case['id']}")


def test_weaknesses_without_text():
    with TestClient(app) as client:
        case = _case(client)
        r = client.get(f"/insights/weaknesses?case_id={case['id']}").json()
        assert r["weaknesses"] is None and r["reason"] == "no_text"
        client.delete(f"/cases/{case['id']}")
