import contextlib
import uuid

from fastapi.testclient import TestClient

from app.main import app


@contextlib.contextmanager
def _two_cases(client, tmp_path):
    """Two cases, each with one evidence file carrying a unique marker.
    Cleans up the evidence afterwards so it can't perturb order-sensitive
    tests that scan the whole DB (e.g. contradictions)."""
    m_a = "alpha" + uuid.uuid4().hex[:8]
    m_b = "beta" + uuid.uuid4().hex[:8]
    case_a = client.post("/cases", json={"name": f"Case A {m_a}"}).json()["id"]
    case_b = client.post("/cases", json={"name": f"Case B {m_b}"}).json()["id"]

    pa = tmp_path / f"a_{m_a}.txt"
    pa.write_text(f"העד ראה את דוד לוי בתאריך 2024-01-05. סימן {m_a}", encoding="utf-8")
    pb = tmp_path / f"b_{m_b}.txt"
    pb.write_text(f"העד ראה את משה כהן בתאריך 2024-09-09. סימן {m_b}", encoding="utf-8")

    ev_a = client.post("/evidence/import-file", json={"path": str(pa), "case_id": case_a}).json()
    ev_b = client.post("/evidence/import-file", json={"path": str(pb), "case_id": case_b}).json()
    assert client.get(f"/evidence/{ev_a['id']}").json()["status"] == "indexed"
    assert client.get(f"/evidence/{ev_b['id']}").json()["status"] == "indexed"
    try:
        yield case_a, case_b, m_a, m_b
    finally:
        client.delete(f"/evidence/{ev_a['id']}")
        client.delete(f"/evidence/{ev_b['id']}")


def test_keyword_search_scoped_to_case(tmp_path):
    with TestClient(app) as client, _two_cases(client, tmp_path) as (case_a, case_b, m_a, m_b):
        # searching case A for case B's marker returns nothing
        assert client.get("/search", params={"q": m_b, "case_id": case_a}).json() == []
        # case B finds its own
        assert len(client.get("/search", params={"q": m_b, "case_id": case_b}).json()) == 1
        # unscoped finds it across all cases
        assert len(client.get("/search", params={"q": m_b}).json()) == 1


def test_semantic_search_scoped_to_case(tmp_path):
    with TestClient(app) as client, _two_cases(client, tmp_path) as (case_a, case_b, m_a, m_b):
        results = client.get("/search/semantic", params={"q": m_a, "case_id": case_a}).json()
        assert results and all(m_b not in r["text"] for r in results)


def test_entities_and_timeline_scoped(tmp_path):
    with TestClient(app) as client, _two_cases(client, tmp_path) as (case_a, case_b, m_a, m_b):
        ents_a = client.get("/entities", params={"case_id": case_a, "limit": 500}).json()
        names_a = " ".join(e["entity"] for e in ents_a)
        assert "דוד" in names_a           # case A's person present
        assert "משה" not in names_a       # case B's person must not leak in

        tl_a = client.get("/timeline", params={"case_id": case_a, "limit": 100}).json()
        dates_a = {e["normalized_date"] for e in tl_a}
        assert "2024-01-05" in dates_a
        assert "2024-09-09" not in dates_a


def test_ai_ask_scoped(tmp_path):
    with TestClient(app) as client, _two_cases(client, tmp_path) as (case_a, case_b, m_a, m_b):
        r = client.post("/ai/ask", json={"question": m_b, "case_id": case_a})
        assert r.status_code == 200
        # case A has no evidence matching case B's marker
        assert all(m_b not in (c.get("text") or "") for c in r.json()["citations"])
