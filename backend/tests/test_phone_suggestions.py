import uuid

from fastapi.testclient import TestClient

from app.main import app


def test_suggests_phone_near_person_name(tmp_path):
    with TestClient(app) as client:
        marker = uuid.uuid4().hex[:8]
        case_id = client.post("/cases", json={"name": f"Phones {marker}"}).json()["id"]

        # evidence text places a phone right after a name
        p = tmp_path / f"contacts_{marker}.txt"
        p.write_text(
            f"דוד לוי מסר את מספר הטלפון שלו 052-1234567 לחוקר. {marker}\n"
            f"אדם אחר לגמרי ללא טלפון בסביבה.",
            encoding="utf-8",
        )
        ev = client.post("/evidence/import-file", json={"path": str(p), "case_id": case_id}).json()
        assert client.get(f"/evidence/{ev['id']}").json()["status"] == "indexed"

        # a person the phone should attach to
        david = client.post("/persons", json={"case_id": case_id, "name": "דוד לוי"}).json()["id"]

        suggestions = client.get("/persons/suggest-phone-links", params={"case_id": case_id}).json()
        assert suggestions, "expected at least one phone suggestion"
        top = suggestions[0]
        assert top["person_id"] == david
        assert "1234567" in top["phone"]
        assert 0.5 <= top["confidence"] <= 1.0

        # accepting = create the phone link
        client.post(f"/persons/{david}/links", json={"kind": "phone", "value": top["phone"]})

        # once linked, it is no longer suggested
        again = client.get("/persons/suggest-phone-links", params={"case_id": case_id}).json()
        assert not any(s["person_id"] == david and "1234567" in s["phone"] for s in again)

        client.delete(f"/cases/{case_id}")


def test_no_persons_no_suggestions(tmp_path):
    with TestClient(app) as client:
        case_id = client.post("/cases", json={"name": f"empty {uuid.uuid4().hex[:6]}"}).json()["id"]
        assert client.get("/persons/suggest-phone-links", params={"case_id": case_id}).json() == []
        client.delete(f"/cases/{case_id}")
