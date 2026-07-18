"""transcribe_guarded routes small files (and the default-off case) to the fast
in-process path, and hard-kills a large file's child process on timeout so a
stuck-in-segment hang can't wedge the queue."""
import subprocess

from app.services import transcription_service as ts


def test_default_off_always_in_process(monkeypatch, tmp_path):
    monkeypatch.setattr(ts, "TRANSCRIBE_SUBPROCESS", False)
    called = {}

    def _mock(p):
        called["in_process"] = True
        return []
    monkeypatch.setattr(ts, "transcribe_to_chunks", _mock)
    f = tmp_path / "big.wav"
    f.write_bytes(b"x" * (10 * 1024 * 1024))  # 10MB "large", but the flag is off
    assert ts.transcribe_guarded(f) == []
    assert called["in_process"] is True


def test_small_file_stays_in_process_even_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(ts, "TRANSCRIBE_SUBPROCESS", True)
    monkeypatch.setattr(ts, "TRANSCRIBE_SUBPROCESS_MIN_MB", 3)
    monkeypatch.setattr(ts, "transcribe_to_chunks", lambda p: ["in_process"])
    monkeypatch.setattr(ts, "_transcribe_subprocess", lambda p: ["SUBPROCESS"])
    f = tmp_path / "note.opus"
    f.write_bytes(b"x" * 50_000)  # 50KB tiny voice note
    assert ts.transcribe_guarded(f) == ["in_process"]


def test_large_file_hard_timeout_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(ts, "TRANSCRIBE_SUBPROCESS", True)
    monkeypatch.setattr(ts, "TRANSCRIBE_SUBPROCESS_MIN_MB", 3)
    monkeypatch.setattr(ts, "_load_whisper", type("C", (), {"cache_clear": staticmethod(lambda: None)}))
    monkeypatch.setattr(ts, "_probe_media", lambda p: (True, 60.0))

    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="worker", timeout=k.get("timeout"))
    monkeypatch.setattr(subprocess, "run", fake_run)

    f = tmp_path / "call.wav"
    f.write_bytes(b"x" * (5 * 1024 * 1024))  # 5MB, large
    assert ts.transcribe_guarded(f) == []  # hung file abandoned, queue advances
