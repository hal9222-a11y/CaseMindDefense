import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import evidence_service
from app.services.transcription_service import _fmt


def _fake_wav(tmp_path, marker):
    p = tmp_path / f"wiretap_{marker}.wav"
    # marker in the content too: identical bytes would dedupe by SHA256
    p.write_bytes(b"RIFF....WAVEfmt fake audio " + marker.encode())
    return p


def test_media_transcribed_with_time_citations(tmp_path, monkeypatch):
    marker = uuid.uuid4().hex
    monkeypatch.setattr(
        evidence_service,
        "transcribe_to_chunks",
        lambda path: [
            {"text": f"החשוד אמר שהכסף אצל דוד {marker}", "source_location": "time:00:12-01:45"},
            {"text": f"קבעו פגישה ליום שלישי {marker}", "source_location": "time:01:46-03:02"},
        ],
    )
    with TestClient(app) as client:
        p = _fake_wav(tmp_path, marker)
        r = client.post("/evidence/import-file", json={"path": str(p)})
        assert r.status_code == 200
        ev_id = r.json()["id"]

        final = client.get(f"/evidence/{ev_id}").json()
        assert final["status"] == "transcribed"

        results = client.get("/search", params={"q": marker, "limit": 5}).json()
        assert len(results) == 2
        assert all(res["source_location"].startswith("time:") for res in results)


def test_media_without_whisper_gets_clear_status(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence_service, "transcribe_to_chunks", lambda path: None)
    with TestClient(app) as client:
        p = _fake_wav(tmp_path, uuid.uuid4().hex)
        r = client.post("/evidence/import-file", json={"path": str(p)})
        final = client.get(f"/evidence/{r.json()['id']}").json()
        assert final["status"] == "transcription_unavailable"


def test_untranscribable_media_returns_empty_not_none(monkeypatch):
    # whisper is available but the file has no usable audio -> [] (caller
    # maps to no_text_found), not None (transcription_unavailable)
    from app.services import transcription_service

    class Boom:
        def transcribe(self, *a, **k):
            raise IndexError("tuple index out of range")  # no-audio signature

    monkeypatch.setattr(transcription_service, "_load_whisper", lambda: Boom())
    from pathlib import Path

    assert transcription_service.transcribe_to_chunks(Path("x.mp4")) == []


def test_silent_media_marked_no_text(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence_service, "transcribe_to_chunks", lambda path: [])
    with TestClient(app) as client:
        p = _fake_wav(tmp_path, uuid.uuid4().hex)
        r = client.post("/evidence/import-file", json={"path": str(p)})
        final = client.get(f"/evidence/{r.json()['id']}").json()
        assert final["status"] == "no_text_found"


def test_time_formatting():
    assert _fmt(0) == "00:00"
    assert _fmt(75.9) == "01:15"
    assert _fmt(3671) == "61:11"
