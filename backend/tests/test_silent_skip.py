"""Silent-skip: a fast header probe drops no-audio and trivially-short media
before the transcription pipeline runs, so a phone dump full of muted video
clips doesn't burn GPU time producing nothing."""
import wave
from pathlib import Path
from unittest.mock import patch

from app.services import transcription_service as ts


def _make_wav(path: Path, seconds: float, rate: int = 16000) -> None:
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


def test_probe_reads_audio_duration_without_decode(tmp_path):
    p = tmp_path / "voice.wav"
    _make_wav(p, seconds=1.5)
    has_audio, duration = ts._probe_media(p)
    assert has_audio
    assert 1.3 < duration < 1.7  # ~1.5s from the header


def test_skip_reasons():
    with patch.object(ts, "SKIP_SILENT", True):
        # no audio stream -> skip
        with patch.object(ts, "_probe_media", return_value=(False, 0.0)):
            assert ts._silent_skip_reason(Path("x.mp4")) == "no audio stream"
        # audio present but a fraction of a second -> skip
        with patch.object(ts, "_probe_media", return_value=(True, 0.2)):
            assert "too short" in ts._silent_skip_reason(Path("x.mp4"))
        # a real recording -> transcribe it
        with patch.object(ts, "_probe_media", return_value=(True, 42.0)):
            assert ts._silent_skip_reason(Path("x.mp4")) is None
        # unprobeable (0.0 duration, has audio) -> do NOT skip on a guess
        with patch.object(ts, "_probe_media", return_value=(True, 0.0)):
            assert ts._silent_skip_reason(Path("x.mp4")) is None


def test_skip_can_be_disabled():
    with patch.object(ts, "SKIP_SILENT", False):
        with patch.object(ts, "_probe_media", return_value=(False, 0.0)):
            assert ts._silent_skip_reason(Path("x.mp4")) is None


def test_transcribe_skips_without_loading_whisper(tmp_path):
    # a no-audio file must return [] WITHOUT ever loading the model
    p = tmp_path / "muted.mp4"
    p.write_bytes(b"not really media")
    with patch.object(ts, "_silent_skip_reason", return_value="no audio stream"), \
         patch.object(ts, "_load_whisper") as load:
        assert ts.transcribe_to_chunks(p) == []
        load.assert_not_called()


def test_vad_skips_no_speech_clip_before_transcribing(tmp_path):
    # header passes (has audio, long enough) but VAD finds no speech -> skip,
    # and Whisper's transcribe is NEVER called
    p = tmp_path / "music.mp4"
    p.write_bytes(b"x")
    dummy_model = object()
    import numpy as np
    silent_audio = np.zeros(16000, dtype=np.float32)
    with patch.object(ts, "SKIP_SILENT", True), \
         patch.object(ts, "_silent_skip_reason", return_value=None), \
         patch.object(ts, "_load_whisper", return_value=dummy_model), \
         patch.object(ts, "_decode_and_vad", return_value=(silent_audio, False)):
        assert ts.transcribe_to_chunks(p) == []


def test_vad_reuses_decoded_array_for_speech(tmp_path):
    # VAD finds speech -> Whisper gets the SAME array, with vad_filter OFF
    p = tmp_path / "voice.mp4"
    p.write_bytes(b"x")
    import numpy as np
    audio = np.ones(16000, dtype=np.float32)

    class FakeInfo:
        language = "he"

    calls = {}

    class FakeModel:
        def transcribe(self, source, vad_filter):
            calls["source_is_array"] = isinstance(source, np.ndarray)
            calls["vad_filter"] = vad_filter
            return iter([]), FakeInfo()

    with patch.object(ts, "SKIP_SILENT", True), \
         patch.object(ts, "_silent_skip_reason", return_value=None), \
         patch.object(ts, "_load_whisper", return_value=FakeModel()), \
         patch.object(ts, "_decode_and_vad", return_value=(audio, True)):
        ts.transcribe_to_chunks(p)
    assert calls["source_is_array"] is True   # no second decode
    assert calls["vad_filter"] is False       # no second VAD
