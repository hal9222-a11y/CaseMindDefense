import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services.entity_service import PHONE_RE
from app.services.timeline_service import SNIPPET_RADIUS, _snippet


def test_phone_regex_matches_international_and_local():
    text = "call +972-52-123-4567 or 052-1234567"
    matches = PHONE_RE.findall(text)
    assert len(matches) == 2


def test_timeline_snippet_is_bounded():
    text = "x" * 1000 + " 2024-01-15 " + "y" * 1000
    start = text.index("2024-01-15")
    snippet = _snippet(text, start, start + 10)
    assert "2024-01-15" in snippet
    assert len(snippet) <= 2 * SNIPPET_RADIUS + 10 + len("......")
    assert snippet.startswith("...") and snippet.endswith("...")


def test_ai_ask_respects_limit(tmp_path):
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        for i in range(3):
            p = tmp_path / f"doc_{i}_{marker}.txt"
            p.write_text(f"the suspect met the witness {marker} meeting number {i}", encoding="utf-8")
            assert client.post("/evidence/import-file", json={"path": str(p)}).status_code == 200

        r = client.post("/ai/ask", json={"question": f"witness {marker}", "limit": 1})
        assert r.status_code == 200
        assert len(r.json()["citations"]) <= 1

        assert client.post("/ai/ask", json={"question": "x", "limit": 0}).status_code == 422


def test_keyword_search_finds_substring(tmp_path):
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        p = tmp_path / f"kw_{marker}.txt"
        p.write_text(f"unique keyword {marker} appears here", encoding="utf-8")
        assert client.post("/evidence/import-file", json={"path": str(p)}).status_code == 200

        r = client.get("/search", params={"q": marker, "limit": 5})
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["filename"] == f"kw_{marker}.txt"
