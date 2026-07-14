import threading
import time
import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import get_engine
from app.main import app
from app.models.evidence import Evidence
from app.services import llm_service, translation_worker

RUSSIAN = "Юлия встретила Дмитрия возле банка в понедельник вечером. " * 60


def _import(client, tmp_path, text):
    marker = uuid.uuid4().hex
    p = tmp_path / f"d_{marker}.txt"
    p.write_text(f"{text}\nref {marker}", encoding="utf-8")
    r = client.post("/evidence/import-file", json={"path": str(p)})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_background_work_waits_for_the_user(monkeypatch):
    # Ollama serves one request at a time: a user's question must not queue
    # behind hours of background translation (measured 219s before this)
    monkeypatch.setattr(llm_service, "active_model", lambda: "fake")
    monkeypatch.setattr(llm_service, "_chat_call", lambda model, messages: "ok")

    order: list[str] = []
    user_done = threading.Event()

    def user_call():
        # hold an interactive call open for a moment
        def slow(model, messages):
            time.sleep(0.3)
            order.append("user")
            return "answer"
        monkeypatch.setattr(llm_service, "_chat_call", slow)
        llm_service._chat([{"role": "user", "content": "hi"}])
        user_done.set()

    def background_call():
        llm_service.mark_background()
        llm_service.wait_until_user_idle(timeout=5)
        order.append("background")

    user = threading.Thread(target=user_call)
    user.start()
    time.sleep(0.05)  # make sure the user's call is in flight
    bg = threading.Thread(target=background_call)
    bg.start()
    user.join(); bg.join()

    assert user_done.is_set()
    assert order == ["user", "background"], order  # the user went first


def test_a_long_document_resumes_after_a_restart(tmp_path, monkeypatch):
    # the 83k chat was restarted from scratch on every backend restart and so
    # never finished. Progress must be saved per chunk.
    calls = {"n": 0}

    def flaky_chunk(chunk, target="Hebrew"):
        calls["n"] += 1
        if calls["n"] == 2:
            return None  # simulate the backend dying mid-document
        return "תורגם"

    monkeypatch.setattr(llm_service, "translate_chunk", flaky_chunk)
    with TestClient(app) as client:
        ev_id = _import(client, tmp_path, RUSSIAN)

        with Session(get_engine()) as s:
            assert translation_worker.translate_one(s, s.get(Evidence, ev_id)) == "failed"
        with Session(get_engine()) as s:
            ev = s.get(Evidence, ev_id)
            partial = ev.translation_chunks_done
            assert partial >= 1                       # first chunk was kept
            assert ev.translation_status == "pending"  # picked up again, not lost

        # "restart": the worker resumes instead of redoing the finished chunks
        monkeypatch.setattr(llm_service, "translate_chunk", lambda c, target="Hebrew": "תורגם")
        with Session(get_engine()) as s:
            assert translation_worker.translate_one(s, s.get(Evidence, ev_id)) == "done"
        with Session(get_engine()) as s:
            ev = s.get(Evidence, ev_id)
            assert ev.translation_status == "done"
            assert ev.translation_chunks_done > partial
