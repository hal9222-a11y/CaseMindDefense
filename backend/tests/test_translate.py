import uuid

from fastapi.testclient import TestClient

from app.api.persons import _hebrew_reading
from app.main import app
from app.models.evidence import PersonLink
from app.services import llm_service


def test_translate_uses_llm(monkeypatch):
    monkeypatch.setattr(llm_service, "translate", lambda text, target="Hebrew": "יוליה פגשה את דמיטרי")
    monkeypatch.setattr(llm_service, "active_model", lambda: "aya-expanse:8b")
    with TestClient(app) as client:
        r = client.post("/translate", json={"text": "Юлия встретила Дмитрия"})
        assert r.status_code == 200
        body = r.json()
        assert "יוליה" in body["translated"]
        assert body["model"] == "aya-expanse:8b"


def test_translate_without_llm_returns_503(monkeypatch):
    # translation has no offline fallback — say so instead of failing silently
    monkeypatch.setattr(llm_service, "translate", lambda text, target="Hebrew": None)
    with TestClient(app) as client:
        r = client.post("/translate", json={"text": "Юлия"})
        assert r.status_code == 503


def test_translate_empty_text_is_a_noop():
    with TestClient(app) as client:
        r = client.post("/translate", json={"text": "   "})
        assert r.status_code == 200
        assert r.json()["translated"] == ""


def test_hebrew_reading_only_for_cyrillic_names():
    hebrew_alias = PersonLink(person_id=1, kind="alias", value="יוליה")
    nickname = PersonLink(person_id=1, kind="alias", value="Юля")
    # Cyrillic name + a Hebrew alias -> that alias is the Hebrew reading
    assert _hebrew_reading("Юлия", [nickname, hebrew_alias]) == "יוליה"
    # Cyrillic name with no Hebrew alias yet
    assert _hebrew_reading("Юлия", [nickname]) is None
    # a Hebrew/Latin name needs no reading beside it
    assert _hebrew_reading("דוד לוי", [hebrew_alias]) is None


def test_translate_names_adds_hebrew_alias_for_russian_person(monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    monkeypatch.setattr(llm_service, "to_hebrew_name", lambda name: "דמיטרי")
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"case_{uuid.uuid4().hex}"}).json()
        person = client.post(
            "/persons",
            json={"case_id": case["id"], "name": "Дмитрий", "description": "", "in_evidence": False},
        ).json()
        assert person["name_he"] is None  # nothing stored yet

        result = client.post("/persons/translate-names", params={"case_id": case["id"]}).json()
        assert result["count"] == 1

        # the Hebrew reading now rides along with the person, beside the Russian name
        people = client.get("/persons", params={"case_id": case["id"]}).json()
        assert people[0]["name_he"] == "דמיטרי"

        # running it again is a no-op (doesn't duplicate the alias)
        again = client.post("/persons/translate-names", params={"case_id": case["id"]}).json()
        assert again["count"] == 0


def test_translate_names_without_llm_returns_503(monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: False)
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"case_{uuid.uuid4().hex}"}).json()
        r = client.post("/persons/translate-names", params={"case_id": case["id"]})
        assert r.status_code == 503
