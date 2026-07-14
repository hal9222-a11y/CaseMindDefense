import uuid

from fastapi.testclient import TestClient

from app.main import app


def _import(client, tmp_path, text: str) -> int:
    marker = uuid.uuid4().hex
    p = tmp_path / f"d_{marker}.txt"
    p.write_text(f"{text}\nref {marker}", encoding="utf-8")
    r = client.post("/evidence/import-file", json={"path": str(p)})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_absent_phone_number_returns_nothing(tmp_path):
    # the bug: searching a number that is NOT in the evidence returned ten
    # confident-looking hits at ~0.82. An investigator could conclude the number
    # appears in the material. Absence must read as absence.
    with TestClient(app) as client:
        _import(client, tmp_path, "העד מסר כי ראה רכב לבן ליד הבית בשעה 22:00.")
        hits = client.get(
            "/search/semantic", params={"q": "0524657474", "limit": 10}
        ).json()
        assert hits == []


def test_present_phone_number_is_found_exactly(tmp_path):
    with TestClient(app) as client:
        ev_id = _import(client, tmp_path, "Позвони Юле: 052-465-7474 вечером.")
        hits = client.get(
            "/search/semantic", params={"q": "0524657474", "limit": 10}
        ).json()
        # formatting differs (052-465-7474 vs 0524657474) — the digits are what matter
        assert [h["evidence_id"] for h in hits] == [ev_id]
        assert hits[0]["match"] == "exact"
        assert hits[0]["score"] == 1.0


def test_word_queries_still_use_meaning(tmp_path):
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        _import(client, tmp_path, f"The witness saw a white vehicle. {marker}")
        hits = client.get(
            "/search/semantic", params={"q": f"white car {marker}", "limit": 5}
        ).json()
        assert hits, "semantic search must still work for ordinary text"
        assert hits[0]["score"] < 1.0  # a similarity, not an exact match
