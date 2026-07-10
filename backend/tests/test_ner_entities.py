import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import ner_service


class FakeNer:
    def __call__(self, text):
        if "דוד לוי" in text:
            return [
                {"word": "דוד לוי", "score": 0.98, "entity_group": "PER"},
                {"word": "תל אביב", "score": 0.93, "entity_group": "GPE"},
                {"word": "רעש", "score": 0.2, "entity_group": "ORG"},  # below threshold
            ]
        return []


def test_model_entities_stored_and_aggregated(tmp_path, monkeypatch):
    monkeypatch.setattr(ner_service, "_load_ner", lambda: FakeNer())
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        p = tmp_path / f"ner_{marker}.txt"
        p.write_text(f"העד דוד לוי ראה את החשוד בתל אביב. טלפון 052-1234567. {marker}", encoding="utf-8")
        assert client.post("/evidence/import-file", json={"path": str(p)}).status_code == 200

        entities = client.get("/entities", params={"limit": 500}).json()
        by_text = {(e["entity"], e["type"]) for e in entities}
        assert ("דוד לוי", "person") in by_text
        assert ("תל אביב", "location") in by_text
        assert any(t == "phone" for _, t in by_text)
        assert ("רעש", "organization") not in by_text  # low score filtered


def test_regex_fallback_when_model_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ner_service, "_load_ner", lambda: None)
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        p = tmp_path / f"fallback_{marker}.txt"
        p.write_text(f"הנאשם פגש את העד. Phone 052-7654321. {marker}", encoding="utf-8")
        assert client.post("/evidence/import-file", json={"path": str(p)}).status_code == 200

        entities = client.get("/entities", params={"limit": 500}).json()
        types = {e["type"] for e in entities}
        assert "phone" in types
        assert "hebrew_term" in types


def test_entity_graph_connects_cooccurring_entities(tmp_path, monkeypatch):
    monkeypatch.setattr(ner_service, "_load_ner", lambda: FakeNer())
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        p = tmp_path / f"graph_{marker}.txt"
        # both entities in one evidence -> expect an edge between them
        p.write_text(f"העד דוד לוי נראה בתל אביב. {marker}", encoding="utf-8")
        assert client.post("/evidence/import-file", json={"path": str(p)}).status_code == 200

        graph = client.get("/entities/graph", params={"max_nodes": 50}).json()
        names = {n["entity"] for n in graph["nodes"]}
        assert {"דוד לוי", "תל אביב"} <= names
        assert any(
            {e["a"], e["b"]} == {"דוד לוי", "תל אביב"} for e in graph["edges"]
        )


def test_reindex_replaces_entities(tmp_path, monkeypatch):
    monkeypatch.setattr(ner_service, "_load_ner", lambda: FakeNer())
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        p = tmp_path / f"reidx_{marker}.txt"
        p.write_text(f"העד דוד לוי היה שם. {marker}", encoding="utf-8")
        ev = client.post("/evidence/import-file", json={"path": str(p)}).json()

        def count_david():
            ents = client.get("/entities", params={"limit": 500}).json()
            return sum(e["count"] for e in ents if e["entity"] == "דוד לוי")

        before = count_david()
        assert before >= 1
        client.post(f"/evidence/{ev['id']}/reindex")
        assert count_david() == before  # replaced, not duplicated
