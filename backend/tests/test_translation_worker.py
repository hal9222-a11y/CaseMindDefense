import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import get_engine
from app.main import app
from app.models.evidence import Evidence
from app.services import llm_service, translation_worker


def _import(client, tmp_path, text: str) -> int:
    # unique marker: identical content across tests would hit SHA256 dedupe (409)
    marker = uuid.uuid4().hex
    p = tmp_path / f"doc_{marker}.txt"
    p.write_text(f"{text}\nref {marker}", encoding="utf-8")
    r = client.post("/evidence/import-file", json={"path": str(p)})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _run_worker_once(evidence_id: int) -> str:
    with Session(get_engine()) as session:
        return translation_worker.translate_one(session, session.get(Evidence, evidence_id))


def test_russian_document_is_translated_and_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_service, "translate_chunk", lambda chunk, target="Hebrew": "יוליה פגשה את דמיטרי")
    with TestClient(app) as client:
        ev_id = _import(client, tmp_path, "Юлия встретила Дмитрия возле банка в понедельник вечером.")
        assert _run_worker_once(ev_id) == "done"

        # the preview gets it instantly — no waiting on the model
        body = client.get(f"/evidence/{ev_id}/content").json()
        assert body["translation_status"] == "done"
        assert "יוליה" in body["translation"]


def test_hebrew_document_is_not_translated(tmp_path, monkeypatch):
    # an hour of GPU time must not be spent on a file that needs nothing
    called = []
    monkeypatch.setattr(llm_service, "translate_chunk",
                        lambda chunk, target="Hebrew": called.append(chunk) or "x")
    with TestClient(app) as client:
        ev_id = _import(client, tmp_path, "העד מסר כי ראה רכב לבן חונה ליד הבית בשעה 22:00.")
        assert _run_worker_once(ev_id) == "not_needed"
        assert called == []


def test_failure_leaves_it_queued_for_retry(tmp_path, monkeypatch):
    # LLM down mid-backlog: the file must stay claimable, not be marked done
    monkeypatch.setattr(llm_service, "translate_chunk", lambda chunk, target="Hebrew": None)
    with TestClient(app) as client:
        ev_id = _import(client, tmp_path, "Юлия встретила Дмитрия возле банка в понедельник вечером.")
        assert _run_worker_once(ev_id) == "failed"
        with Session(get_engine()) as session:
            # nothing was translated, so it is still unclaimed and gets retried
            assert session.get(Evidence, ev_id).translation_status == ""


def test_status_reports_the_translation_backlog(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_service, "translate_chunk", lambda chunk, target="Hebrew": "תורגם")
    with TestClient(app) as client:
        ev_id = _import(client, tmp_path, "Юлия встретила Дмитрия возле банка в понедельник вечером.")
        before = client.get("/status").json()
        assert before["to_translate"] >= 1

        _run_worker_once(ev_id)
        after = client.get("/status").json()
        assert after["translated"] >= 1
        assert after["to_translate"] == before["to_translate"] - 1
