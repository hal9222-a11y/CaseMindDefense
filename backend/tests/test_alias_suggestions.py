import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import ner_service


class FakeNer:
    def __call__(self, text):
        found = []
        for name in ("דוד לוי", "דוד", "דודי"):
            if name in text:
                found.append({"word": name, "score": 0.97, "entity_group": "PER"})
        return found


def test_suggests_token_and_prefix_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(ner_service, "_load_ner", lambda: FakeNer())
    with TestClient(app) as client:
        marker = uuid.uuid4().hex[:8]
        case_id = client.post("/cases", json={"name": f"Alias {marker}"}).json()["id"]

        p = tmp_path / f"names_{marker}.txt"
        p.write_text(
            f"דוד לוי נראה בזירה. חבריו קוראים לו דודי. דוד הגיע מאוחר. {marker}",
            encoding="utf-8",
        )
        ev = client.post("/evidence/import-file", json={"path": str(p), "case_id": case_id}).json()
        assert client.get(f"/evidence/{ev['id']}").json()["status"] == "indexed"

        person = client.post("/persons", json={"case_id": case_id, "name": "דוד לוי"}).json()["id"]

        suggestions = client.get("/persons/suggest-aliases", params={"case_id": case_id}).json()
        aliases = {s["alias"]: s for s in suggestions if s["person_id"] == person}
        assert "דוד" in aliases and aliases["דוד"]["confidence"] == 0.9   # token of full name
        assert "דודי" in aliases and aliases["דודי"]["confidence"] == 0.6  # prefix nickname

        # accept one, and it stops being suggested
        client.post(f"/persons/{person}/links", json={"kind": "alias", "value": "דוד"})
        after = client.get("/persons/suggest-aliases", params={"case_id": case_id}).json()
        assert not any(s["person_id"] == person and s["alias"] == "דוד" for s in after)

        client.delete(f"/cases/{case_id}")


def test_no_persons_no_alias_suggestions():
    with TestClient(app) as client:
        case_id = client.post("/cases", json={"name": f"e {uuid.uuid4().hex[:6]}"}).json()["id"]
        assert client.get("/persons/suggest-aliases", params={"case_id": case_id}).json() == []
        client.delete(f"/cases/{case_id}")
