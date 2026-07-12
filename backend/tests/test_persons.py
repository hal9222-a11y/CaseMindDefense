import uuid

from fastapi.testclient import TestClient

from app.main import app


def _case(client):
    return client.post("/cases", json={"name": f"Persons {uuid.uuid4().hex[:8]}"}).json()["id"]


def test_create_list_update_delete_person():
    with TestClient(app) as client:
        case_id = _case(client)

        p = client.post("/persons", json={
            "case_id": case_id, "name": "אמיר גורי", "description": "הנאשם",
        }).json()
        assert p["name"] == "אמיר גורי" and p["in_evidence"] is True

        listed = client.get("/persons", params={"case_id": case_id}).json()
        assert len(listed) == 1

        upd = client.patch(f"/persons/{p['id']}", json={"description": "נאשם ראשי"}).json()
        assert upd["description"] == "נאשם ראשי"

        assert client.delete(f"/persons/{p['id']}").status_code == 200
        assert client.get("/persons", params={"case_id": case_id}).json() == []


def test_add_alias_phone_and_relation_links():
    with TestClient(app) as client:
        case_id = _case(client)
        david = client.post("/persons", json={"case_id": case_id, "name": "דוד לוי"}).json()
        # a person NOT in the evidence, described by the user
        brother = client.post("/persons", json={
            "case_id": case_id, "name": "יוסי לוי",
            "description": "אחיו של דוד, לא מופיע בחומרים", "in_evidence": False,
        }).json()

        client.post(f"/persons/{david['id']}/links", json={"kind": "alias", "value": "דודי"})
        client.post(f"/persons/{david['id']}/links", json={"kind": "phone", "value": "052-1234567"})
        result = client.post(f"/persons/{david['id']}/links", json={
            "kind": "relation", "related_person_id": brother["id"], "value": "אח",
        }).json()

        kinds = {ln["kind"] for ln in result["links"]}
        assert kinds == {"alias", "phone", "relation"}
        rel = next(ln for ln in result["links"] if ln["kind"] == "relation")
        assert rel["related_person_id"] == brother["id"] and rel["value"] == "אח"

        # remove one link
        alias_link = next(ln for ln in result["links"] if ln["kind"] == "alias")
        after = client.delete(f"/persons/{david['id']}/links/{alias_link['id']}").json()
        assert "alias" not in {ln["kind"] for ln in after["links"]}


def test_link_validation():
    with TestClient(app) as client:
        case_id = _case(client)
        p = client.post("/persons", json={"case_id": case_id, "name": "X"}).json()
        assert client.post(f"/persons/{p['id']}/links", json={"kind": "bogus"}).status_code == 422
        assert client.post(f"/persons/{p['id']}/links", json={"kind": "photo"}).status_code == 422
        assert client.post(f"/persons/{p['id']}/links", json={"kind": "relation"}).status_code == 422


def test_deleting_person_removes_relations_pointing_at_them():
    with TestClient(app) as client:
        case_id = _case(client)
        a = client.post("/persons", json={"case_id": case_id, "name": "A"}).json()
        b = client.post("/persons", json={"case_id": case_id, "name": "B"}).json()
        client.post(f"/persons/{a['id']}/links", json={
            "kind": "relation", "related_person_id": b["id"], "value": "חבר",
        })
        # deleting B must drop A's relation link that referenced B
        client.delete(f"/persons/{b['id']}")
        a_after = client.get("/persons", params={"case_id": case_id}).json()[0]
        assert a_after["links"] == []


def test_deleting_case_removes_its_persons(tmp_path):
    with TestClient(app) as client:
        case_id = _case(client)
        client.post("/persons", json={"case_id": case_id, "name": "ephemeral"})
        client.delete(f"/cases/{case_id}")
        # the persons endpoint requires a case; the case is gone, so listing
        # by that id returns empty
        assert client.get("/persons", params={"case_id": case_id}).json() == []


def test_person_graph_has_nodes_and_labelled_edges():
    with TestClient(app) as client:
        case_id = _case(client)
        a = client.post("/persons", json={"case_id": case_id, "name": "אמיר"}).json()["id"]
        b = client.post("/persons", json={"case_id": case_id, "name": "דוד",
                                          "in_evidence": False}).json()["id"]
        client.post(f"/persons/{a}/links", json={
            "kind": "relation", "related_person_id": b, "value": "אח"})

        g = client.get("/persons/graph", params={"case_id": case_id}).json()
        assert {n["id"] for n in g["nodes"]} == {a, b}
        assert any(n["id"] == b and n["in_evidence"] is False for n in g["nodes"])
        assert g["edges"] == [{"a": a, "b": b, "label": "אח"}]
