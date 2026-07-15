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
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".3gp", ".webm", ".wmv", ".flv", ".vob", ".mpg", ".mpeg", ".m4v"}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# "small" is multilingual (Hebrew/Russian/English) and CPU-viable.
# Hebrew-tuned alternative: an ivrit.ai faster-whisper model name.
WHISPER_MODEL = os.getenv("CASEMIND_WHISPER_MODEL", "small")
# "auto" uses the NVIDIA GPU when present — measured 37x faster (a voice message
# 26 min on CPU -> 42 s), which is the difference between a case's 374 voice
# recordings taking a week and taking a night. Force with CASEMIND_WHISPER_DEVICE.
WHISPER_DEVICE = os.getenv("CASEMIND_WHISPER_DEVICE", "auto")
CHUNK_TARGET_CHARS = 1000

# Silent-skip: this case holds ~14,500 videos, most of them short WhatsApp
# clips. Many carry NO audio track at all (a GIF saved as .mp4, a muted clip);
# running the full transcription pipeline on them wastes GPU time to produce
# nothing. A header-only probe (no decode) skips those instantly. Files WITH an
# audio track still go to Whisper, whose VAD already avoids inference on silence.
SKIP_SILENT = os.getenv("CASEMIND_SKIP_SILENT", "1") != "0"
# below this many seconds of audio there is no meaningful speech to find (a
# sticker, a 0.2s notification). Conservative — a one-word "כן" is ~0.5s.
MIN_AUDIO_SECONDS = float(os.getenv("CASEMIND_MIN_AUDIO_SECONDS", "0.4"))


def _probe_media(path: Path) -> tuple[bool, float]:
    """(has_audio_stream, audio_seconds) from the container HEADER only — no
    decode, so it is near-instant. (True, 0.0) when the file can't be probed,
    so an unprobeable file is still handed to Whisper rather than dropped."""
    try:
        import av
    except ImportError:  # pragma: no cover - av ships with faster-whisper
        return (True, 0.0)
    try:
        with av.open(str(path)) as container:
            audio_streams = [s for s in container.streams if s.type == "audio"]
            if not audio_streams:
                return (False, 0.0)
            stream = audio_streams[0]
            duration = 0.0
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            elif container.duration is not None:
                duration = container.duration / av.time_base
            return (True, duration)
    except Exception:
        return (True, 0.0)  # probe failed — do not skip on a guess


def _silent_skip_reason(path: Path) -> str | None:
    """Why to skip this file without transcribing, or None to transcribe it.
    Header-only (no decode): catches files with no audio track or a trivially
    short one. Most phone-clip videos DO carry an audio track, though — the
    speech check in _decode_and_vad catches the silent-but-present ones."""
    if not SKIP_SILENT:
        return None
    has_audio, duration = _probe_media(path)
    if not has_audio:
        return "no audio stream"
    if 0 < duration < MIN_AUDIO_SECONDS:
        return f"audio too short ({duration:.2f}s)"
    return None


def _decode_and_vad(path: Path):
    """Decode the audio ONCE and run voice-activity detection on it.

    Returns (audio_array, has_speech). A phone dump is full of clips whose
    audio track is music or ambient noise with no speech — VAD skips those, and
    when there IS speech we hand Whisper the SAME decoded array (vad_filter off)
    so nothing is decoded or VAD'd twice. (None, True) on any failure, so a file
    we can't pre-check still goes to Whisper the normal way rather than dropped."""
    try:
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except ImportError:  # pragma: no cover
        return (None, True)
    try:
        audio = decode_audio(str(path), sampling_rate=16000)
    except Exception as exc:
        logger.warning("could not decode audio in %s: %s", path.name, exc)
        return (None, True)
    speech = get_speech_timestamps(audio, VadOptions())
    return (audio, bool(speech))


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
    # cheap header probe BEFORE loading/decoding: drop no-audio and trivially
    # short files (thousands of them in a phone dump) without spending GPU time
    skip = _silent_skip_reason(path)
    if skip is not None:
        logger.info("skipping %s: %s", path.name, skip)
        return []  # -> 'no_text_found', same as a silent transcription

    model = _load_whisper()
    if model is None:
        return None  # whisper not installed — a system-level issue

    # decode + VAD once; skip files with no speech, reuse the array otherwise
    source: object = str(path)
    use_vad_filter = True
    if SKIP_SILENT:
        audio, has_speech = _decode_and_vad(path)
        if audio is not None:
            if not has_speech:
                logger.info("skipping %s: no speech detected (VAD)", path.name)
                return []
            source = audio          # transcribe the array we already decoded
            use_vad_filter = False  # and already VAD'd — do not repeat it

    try:
        segments, info = model.transcribe(source, vad_filter=use_vad_filter)
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
