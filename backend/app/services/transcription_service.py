from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov"}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# "small" is multilingual (Hebrew/Russian/English) and CPU-viable.
# Hebrew-tuned alternative: an ivrit.ai faster-whisper model name.
WHISPER_MODEL = os.getenv("CASEMIND_WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("CASEMIND_WHISPER_DEVICE", "cpu")
CHUNK_TARGET_CHARS = 1000


@lru_cache(maxsize=1)
def _load_whisper():
    try:
        from faster_whisper import WhisperModel

        return WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type="int8")
    except Exception as exc:
        logger.warning("Whisper unavailable, media will not be transcribed: %s", exc)
        return None


def _fmt(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def transcribe_to_chunks(path: Path) -> list[dict] | None:
    """Transcribe audio (or a video's audio track) into chunk dicts with
    time-range citations: {'text', 'source_location': 'time:MM:SS-MM:SS'}.

    Returns None when Whisper is unavailable; [] when there is no speech."""
    model = _load_whisper()
    if model is None:
        return None  # whisper not installed — a system-level issue

    try:
        segments, info = model.transcribe(str(path), vad_filter=True)
    except Exception as exc:
        # this file couldn't be transcribed (e.g. a video with no audio
        # track raises IndexError inside faster-whisper). That's not a
        # system problem, so return [] -> 'no_text_found', not None ->
        # 'transcription_unavailable'
        logger.warning("no transcribable audio in %s: %s", path.name, exc)
        return []

    logger.info("transcribing %s (language=%s)", path.name, info.language)

    chunks: list[dict] = []
    buffer: list[str] = []
    start_time: float | None = None
    end_time = 0.0

    def _flush() -> None:
        nonlocal buffer, start_time
        text = " ".join(buffer).strip()
        if text:
            chunks.append(
                {
                    "text": text,
                    "source_location": f"time:{_fmt(start_time or 0)}-{_fmt(end_time)}",
                }
            )
        buffer = []
        start_time = None

    for segment in segments:
        if start_time is None:
            start_time = segment.start
        end_time = segment.end
        buffer.append(segment.text.strip())
        if sum(len(t) for t in buffer) >= CHUNK_TARGET_CHARS:
            _flush()
    _flush()

    return chunks
