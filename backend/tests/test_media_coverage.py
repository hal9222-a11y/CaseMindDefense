import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services.evidence_service import SUPPORTED_EXTENSIONS
from app.services.transcription_service import MEDIA_EXTENSIONS


def test_whatsapp_voice_formats_are_supported():
    # .opus is EVERY WhatsApp voice message. A case with 374 of them imported
    # zero because the format was unlisted.
    assert ".opus" in MEDIA_EXTENSIONS
    assert ".opus" in SUPPORTED_EXTENSIONS
    # other phone/recorder formats seen in real exports
    for ext in (".amr", ".3gp", ".m4a", ".aac"):
        assert ext in SUPPORTED_EXTENSIONS, ext


def test_folder_import_reports_what_it_skipped(tmp_path):
    # the real bug: unsupported files were dropped in silence, so the lawyer had
    # no idea most of the evidence never entered the system
    (tmp_path / "note.txt").write_text("evidence", encoding="utf-8")
    (tmp_path / "voice1.opus").write_bytes(b"\x00\x01")   # now supported
    (tmp_path / "mystery.xyz").write_bytes(b"data")       # genuinely unsupported
    (tmp_path / "archive.zip").write_bytes(b"PK\x03\x04")

    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"c_{uuid.uuid4().hex}"}).json()
        result = client.post(
            "/evidence/import-folder", json={"path": str(tmp_path), "case_id": case["id"]}
        ).json()

        assert result["skipped_unsupported"] == 2          # .xyz and .zip
        assert result["skipped_by_type"].get(".xyz") == 1
        assert result["skipped_by_type"].get(".zip") == 1
        assert ".opus" not in result["skipped_by_type"]    # supported now, not skipped


def test_device_selection_falls_back_to_cpu(monkeypatch):
    # a machine with no usable GPU must still transcribe, just slower — never
    # silently stop transcribing
    import app.services.transcription_service as ts

    ts._load_whisper.cache_clear()
    monkeypatch.setattr(ts, "WHISPER_DEVICE", "auto")

    loaded = {}

    def fake_try_load(device, compute_type):
        loaded["device"] = device
        return object()

    # pretend there is no CUDA device
    import ctranslate2
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 0)
    monkeypatch.setattr(ts, "_try_load", fake_try_load)

    model = ts._load_whisper()
    ts._load_whisper.cache_clear()

    assert model is not None
    assert loaded["device"] == "cpu"
