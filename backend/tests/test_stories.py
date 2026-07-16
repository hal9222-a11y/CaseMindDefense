"""Investigation stories: a titled sequence of notes, pinned evidence and saved
searches — the lawyer's working argument, ordered and editable."""
import uuid

from fastapi.testclient import TestClient

from app.main import app


def test_story_lifecycle(tmp_path):
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"story_{uuid.uuid4().hex[:8]}"}).json()
        story = client.post("/stories", json={"case_id": case["id"], "title": "סתירות בגרסת המתלונן"}).json()

        p = tmp_path / f"ev_{uuid.uuid4().hex}.txt"
        p.write_text("העד מסר גרסה ראשונה.", encoding="utf-8")
        ev = client.post("/evidence/import-file", json={"path": str(p)}).json()

        client.post(f"/stories/{story['id']}/items", json={"kind": "note", "content": "נקודת פתיחה: הגרסה במשטרה"})
        client.post(f"/stories/{story['id']}/items", json={"kind": "evidence", "evidence_id": ev["id"], "content": "ההודעה הראשונה"})
        client.post(f"/stories/{story['id']}/items", json={"kind": "search", "content": "רכב לבן"})

        full = client.get(f"/stories/{story['id']}").json()
        assert full["title"] == "סתירות בגרסת המתלונן"
        assert [i["kind"] for i in full["items"]] == ["note", "evidence", "search"]
        assert full["items"][1]["evidence_filename"] == p.name
        assert [i["position"] for i in full["items"]] == [1, 2, 3]

        # reorder: move the search to the top
        client.patch(f"/stories/{story['id']}/items/{full['items'][2]['id']}", json={"position": 0})
        reordered = client.get(f"/stories/{story['id']}").json()
        assert reordered["items"][0]["kind"] == "search"

        # listing shows item count
        listed = client.get(f"/stories?case_id={case['id']}").json()
        assert listed[0]["items"] == 3

        # invalid inputs
        assert client.post(f"/stories/{story['id']}/items", json={"kind": "bogus"}).status_code == 400
        assert client.post(f"/stories/{story['id']}/items", json={"kind": "evidence", "evidence_id": 999999}).status_code == 404

        # delete cascades
        client.delete(f"/stories/{story['id']}")
        assert client.get(f"/stories/{story['id']}").status_code == 404
        assert client.get(f"/stories?case_id={case['id']}").json() == []
