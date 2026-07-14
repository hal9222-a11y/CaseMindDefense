from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# .opus is how WhatsApp stores EVERY voice message. Leaving it out meant a
# forensic export with 374 voice recordings imported none of them — and the
# folder import said nothing. In a criminal case those recordings can be the
# evidence. .amr/.3gp are what older phones and some call recorders produce.
AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".ogg", ".opus", ".flac",
    ".aac", ".amr", ".3gp", ".3gpp", ".wma", ".webm", ".m4b",
}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".3gp", ".webm", ".wmv", ".flv"}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# "small" is multilingual (Hebrew/Russian/English) and CPU-viable.
# Hebrew-tuned alternative: an ivrit.ai faster-whisper model name.
WHISPER_MODEL = os.getenv("CASEMIND_WHISPER_MODEL", "small")
# "auto" uses the NVIDIA GPU when present — measured 37x faster (a voice message
# 26 min on CPU -> 42 s), which is the difference between a case's 374 voice
# recordings taking a week and taking a night. Force with CASEMIND_WHISPER_DEVICE.
WHISPER_DEVICE = os.getenv("CASEMIND_WHISPER_DEVICE", "auto")
CHUNK_TARGET_CHARS = 1000


def _enable_cuda_dlls() -> None:
    """faster-whisper's CUDA runtime (cuBLAS/cuDNN) ships as pip packages under
    nvidia/*/bin. Those dirs must be on the DLL search path or loading the GPU
    model fails with 'cublas64_12.dll not found'."""
    import glob

    base = os.path.join(os.path.dirname(__file__), "..", "..", ".venv",
                        "Lib", "site-packages", "nvidia")
    bins = sorted({os.path.dirname(p) for p in glob.glob(
        os.path.join(base, "**", "*.dll"), recursive=True)})
    for path in bins:
        try:
            os.add_dll_directory(path)
        except (OSError, AttributeError):
            pass
    if bins:
        os.environ["PATH"] = os.pathsep.join(bins) + os.pathsep + os.environ.get("PATH", "")


def _try_load(device: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(WHISPER_MODEL, device=device, compute_type=compute_type)


@lru_cache(maxsize=1)
def _load_whisper():
    # GPU first (float16), CPU (int8) as the fallback — a machine without a
    # usable GPU still transcribes, just slower.
    want_gpu = WHISPER_DEVICE in ("auto", "cuda")
    if want_gpu:
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                _enable_cuda_dlls()
                model = _try_load("cuda", "float16")
                logger.info("Whisper on GPU (cuda/float16)")
                return model
        except Exception as exc:
            logger.warning("Whisper GPU load failed, falling back to CPU: %s", exc)

    if WHISPER_DEVICE == "cuda":
        # explicitly asked for GPU and it did not work — do not silently pretend
        logger.warning("Whisper GPU requested but unavailable; media not transcribed")
        return None

    try:
        model = _try_load("cpu", "int8")
        logger.info("Whisper on CPU (int8)")
        return model
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
