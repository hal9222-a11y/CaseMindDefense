"""Watchlist: standing queries over the evidence stream. A term added today
must flag material that finishes transcribing weeks from now (scan-at-index),
and material indexed long ago (backfill-on-add)."""
import uuid

from fastapi.testclient import TestClient

from app.main import app


def _case(client, name=None):
    return client.post("/cases", json={"name": name or f"wl_{uuid.uuid4().hex[:8]}"}).json()


def _import(client, tmp_path, text, case_id=None, name=None):
    p = tmp_path / (name or f"doc_{uuid.uuid4().hex}.txt")
    p.write_text(text, encoding="utf-8")
    body = {"path": str(p)}
    if case_id:
        body["case_id"] = case_id
    ev = client.post("/evidence/import-file", json=body).json()
    # index synchronously so the scan-at-index hook runs before we assert
    from sqlmodel import Session

    from app.db import get_engine
    from app.services.evidence_service import index_evidence

    with Session(get_engine()) as session:
        index_evidence(session, ev["id"])
    return ev


def test_scan_at_index_flags_new_evidence(tmp_path):
    with TestClient(app) as client:
        case = _case(client)
        added = client.post("/watchlist", json={"term": "אמיר גורי", "case_id": case["id"]}).json()
        assert added["kind"] == "text" and added["hits"] == 0

        _import(client, tmp_path, "בשיחה הוזכר אמיר גורי ליד הרכב הלבן.", case_id=case["id"])
        hits = client.get(f"/watchlist/hits?case_id={case['id']}&unseen_only=true").json()
        assert len(hits) == 1
        assert "אמיר גורי" in hits[0]["snippet"]
        assert hits[0]["term"] == "אמיר גורי"

        # mark seen -> disappears from the unseen feed
        client.post(f"/watchlist/hits/{hits[0]['id']}/seen")
        assert client.get(f"/watchlist/hits?case_id={case['id']}&unseen_only=true").json() == []


def test_watchlist_scan_failure_never_breaks_indexing(tmp_path, monkeypatch):
    """A crash inside the watchlist scan must not fail — or mislabel — the
    indexing it hangs off of. (Regression: the scan's except-handler referenced
    an undefined `logger`, so a scan failure raised NameError, which propagated
    out and marked already-indexed evidence as text_extraction_failed.)"""
    from sqlmodel import Session

    from app.db import get_engine
    from app.services import evidence_service, watchlist_service

    def boom(*a, **k):
        raise RuntimeError("watchlist exploded")

    monkeypatch.setattr(watchlist_service, "scan_evidence", boom)

    with TestClient(app) as client:
        case = _case(client)
        p = tmp_path / f"doc_{uuid.uuid4().hex}.txt"
        p.write_text("הרכב הלבן חנה ליד הבניין.", encoding="utf-8")
        ev = client.post("/evidence/import-file",
                         json={"path": str(p), "case_id": case["id"]}).json()
        with Session(get_engine()) as session:
            result = evidence_service.index_evidence(session, ev["id"])  # must not raise
            # read status INSIDE the session: the scan's except-handler rolls
            # back, which expires the instance, so it must reload while bound
            assert result.status == "indexed"  # not text_extraction_failed


def test_backfill_flags_already_indexed_evidence(tmp_path):
    with TestClient(app) as client:
        case = _case(client)
        _import(client, tmp_path, "העד ראה את יורי מתרחק מהזירה.", case_id=case["id"])
        added = client.post("/watchlist", json={"term": "יורי", "case_id": case["id"]}).json()
        assert added["hits"] == 1  # found retroactively


def test_phone_terms_match_digits_normalized(tmp_path):
    with TestClient(app) as client:
        case = _case(client)
        added = client.post("/watchlist", json={"term": "0524657474", "case_id": case["id"]}).json()
        assert added["kind"] == "phone"

        _import(client, tmp_path, "תתקשר אליי למספר 052-465-7474 בערב.", case_id=case["id"])
        hits = client.get(f"/watchlist/hits?case_id={case['id']}").json()
        assert len(hits) == 1
        assert "052-465-7474" in hits[0]["snippet"]


def test_no_cross_case_leakage(tmp_path):
    with TestClient(app) as client:
        case_a, case_b = _case(client), _case(client)
        client.post("/watchlist", json={"term": "סמואל", "case_id": case_a["id"]})
        _import(client, tmp_path, "סמואל הופיע בפגישה.", case_id=case_b["id"])
        assert client.get(f"/watchlist/hits?case_id={case_a['id']}").json() == []


def test_duplicate_term_rejected_and_delete_cascades(tmp_path):
    with TestClient(app) as client:
        case = _case(client)
        item = client.post("/watchlist", json={"term": "בדיקה כפולה", "case_id": case["id"]}).json()
        assert client.post("/watchlist", json={"term": "בדיקה כפולה", "case_id": case["id"]}).status_code == 409

        _import(client, tmp_path, "זו בדיקה כפולה של המנגנון.", case_id=case["id"])
        assert len(client.get(f"/watchlist/hits?case_id={case['id']}").json()) == 1
        client.delete(f"/watchlist/{item['id']}")
        assert client.get(f"/watchlist/hits?case_id={case['id']}").json() == []
