import logging

from fastapi.testclient import TestClient

from app.api import ai
from app.main import app


def test_unhandled_error_returns_clean_500_and_logs(monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("simulated failure")

    # the router imports answer_with_evidence by name, so patch it there
    monkeypatch.setattr(ai, "answer_with_evidence", boom)

    # raise_server_exceptions=False so the app's handler runs instead of
    # the exception propagating into the test
    with TestClient(app, raise_server_exceptions=False) as client:
        with caplog.at_level(logging.ERROR, logger="app.request"):
            r = client.post("/ai/ask", json={"question": "x"})

    assert r.status_code == 500
    assert r.json() == {"detail": "internal server error"}
    # the full traceback reached the logger (and thus backend.log)
    assert any("simulated failure" in rec.message or rec.exc_info for rec in caplog.records)


def test_http_exceptions_are_not_swallowed(tmp_path):
    # the global Exception handler must not turn a real 404/409 into a 500
    with TestClient(app) as client:
        assert client.get("/evidence/999999").status_code == 404
        assert client.post(
            "/evidence/import-file", json={"path": "Z:/nope/missing.txt"}
        ).status_code == 404
