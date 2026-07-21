import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import llm_service

# real transliterations observed from the local model on a live case
HEBREW_READING = {
    "Юля": "יוליה",
    "Юлия": "יוליה",
    "Лена": "לונה",
    "Алеся": "אלסיה",
    "Алина": "אלינה",
    "Марина": "מרינה",
}


def _setup(client, chat_text: str, person_name: str):
    case = client.post("/cases", json={"name": f"c_{uuid.uuid4().hex}"}).json()
    import tempfile, pathlib
    p = pathlib.Path(tempfile.mkdtemp()) / "chat.txt"
    p.write_text(chat_text, encoding="utf-8")
    client.post("/evidence/import-file", json={"path": str(p), "case_id": case["id"]})
    person = client.post("/persons", json={
        "case_id": case["id"], "name": person_name, "description": "", "in_evidence": True,
    }).json()
    return case["id"], person["id"]


def test_hebrew_person_is_matched_to_russian_mentions(monkeypatch):
    # the bug: a person recorded as "יוליה" was invisible in Russian evidence,
    # so her phone was never attributed
    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    monkeypatch.setattr(llm_service, "to_hebrew_name", lambda n: HEBREW_READING.get(n, ""))
    with TestClient(app) as client:
        case_id, person_id = _setup(
            client, "Юля сказала позвонить: 052-3545256 завтра вечером.", "יוליה"
        )
        sug = client.get("/persons/suggest-phone-links", params={"case_id": case_id}).json()
        assert len(sug) == 1
        assert sug[0]["person_id"] == person_id
        assert sug[0]["matched_name"] == "Юля"   # matched across scripts
        assert "3545256" in sug[0]["phone"]


def test_another_persons_phone_is_not_attributed(monkeypatch):
    # regression: at a loose threshold, Лена/Алеся/Алина all fuzzy-matched
    # "יוליה" and their phones were attributed to her at up to 100% confidence
    monkeypatch.setattr(llm_service, "ollama_available", lambda: True)
    monkeypatch.setattr(llm_service, "to_hebrew_name", lambda n: HEBREW_READING.get(n, ""))
    with TestClient(app) as client:
        case_id, _ = _setup(
            client, "YULKA: +972 54-9268621 Лена. Алеся 052-1112223. Алина 053-4445556.", "יוליה"
        )
        sug = client.get("/persons/suggest-phone-links", params={"case_id": case_id}).json()
        assert sug == [], f"someone else's phone attributed to יוליה: {sug}"


def test_cross_script_is_skipped_without_llm(monkeypatch):
    monkeypatch.setattr(llm_service, "ollama_available", lambda: False)
    with TestClient(app) as client:
        case_id, _ = _setup(client, "Юля: 052-3545256", "יוליה")
        # no transliteration available -> no cross-script guesses, and no crash
        assert client.get(
            "/persons/suggest-phone-links", params={"case_id": case_id}
        ).json() == []
