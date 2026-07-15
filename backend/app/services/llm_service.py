from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("CASEMIND_OLLAMA_URL", "http://127.0.0.1:11434")
LLM_TIMEOUT_SECONDS = int(os.getenv("CASEMIND_LLM_TIMEOUT", "120"))

# "ollama" (local, private — default) or "gemini" (cloud, fast, sends text to
# Google). Gemini is opt-in: the evidence leaves the machine, so the user turns
# it on deliberately.
LLM_PROVIDER = os.getenv("CASEMIND_LLM_PROVIDER", "ollama").lower()
GEMINI_API_KEY = os.getenv("CASEMIND_GEMINI_API_KEY") or None
GEMINI_MODEL = os.getenv("CASEMIND_GEMINI_MODEL", "gemini-2.0-flash")

# The app auto-selects the best general chat model actually installed in Ollama,
# so a machine with capable models uses them without configuration. Set
# CASEMIND_LLM_MODEL to force a specific model instead.
FORCED_MODEL = os.getenv("CASEMIND_LLM_MODEL") or None

# names/families that aren't general-purpose chat models — never auto-select
_EXCLUDE_RE = re.compile(r"ocr|embed|rerank|whisper|bge|vl|vision|code|guard|cloud", re.I)
# Reasoning models emit a long hidden "thinking" pass before the answer — on
# local hardware that is minutes per call, which reads as "AI timed out" to the
# user. Auto-select must prefer a plain chat model even when a reasoning model
# is bigger (qwen3.5:9b kept beating gemma4:latest on size and timing out).
# ponytail: name heuristic, misses unlisted reasoning families; upgrade path is
# Ollama /api/show "capabilities" (lists "thinking") if this mismatches.
_REASONING_RE = re.compile(r"qwen3|deepseek-r|qwq|magistral|think|reason", re.I)
# largest model to auto-pick: bigger ones give better answers but on local CPU
# a 30B model can take minutes and re-introduce timeouts. Override via env to
# force a bigger model if the machine has the GPU for it.
_SIZE_CEILING_B = float(os.getenv("CASEMIND_LLM_MAX_PARAMS_B", "14"))

SYSTEM_PROMPT = """You are an evidence analysis assistant for a criminal defense team.
You will receive numbered evidence excerpts and a question.

Hard rules:
- Answer ONLY from the evidence excerpts. Never use outside knowledge.
- CITATIONS ARE MANDATORY: every sentence or bullet MUST end with the
  bracketed number of its source excerpt, like [1] or [2][3].
  Example: "הנאשם מכחיש את האישום [2]." An answer without [n] markers
  is invalid.
- If the evidence does not answer the question, reply exactly: NOT_FOUND
- Be concise and factual. No speculation."""

HEBREW_RE = re.compile("[֐-׿]")


_MODEL_TTL = 15.0  # seconds; the status bar polls often, don't hammer Ollama
_model_cache: dict[str, float | str | None] = {"ts": 0.0, "model": None}


def _installed_models() -> list[dict]:
    with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as resp:
        return json.load(resp).get("models", [])


def _size_b(model: dict) -> float:
    """Parameter count in billions, parsed from Ollama's '9.7B' / '494.03M' /
    '1t' strings. 0.0 when unknown."""
    raw = str(model.get("details", {}).get("parameter_size") or "").strip().lower()
    match = re.match(r"([\d.]+)\s*([bmt]?)", raw)
    if not match:
        return 0.0
    value = float(match.group(1))
    return {"m": value / 1000, "t": value * 1000, "b": value, "": value}[match.group(2)]


def _pick_model(installed: list[dict]) -> str | None:
    """Choose which installed model to use: the forced one if set and present,
    else the largest general chat model within the size ceiling (skipping
    OCR/vision/code/embedding models). Falls back to the smallest available if
    every general model exceeds the ceiling, so the user always gets an LLM."""
    if not installed:
        return None
    if FORCED_MODEL:
        base = FORCED_MODEL.split(":")[0]
        forced = next(
            (m["name"] for m in installed
             if m["name"] == FORCED_MODEL or m["name"].split(":")[0] == base),
            None,
        )
        if forced:
            return forced
        # forced model isn't installed (e.g. it was removed) — fall through to
        # auto-select instead of leaving the app with NO AI. A pinned model is a
        # preference, not a reason to have zero LLM when 14 others are present.
        logger.warning(
            "CASEMIND_LLM_MODEL=%s is not installed; auto-selecting instead", FORCED_MODEL
        )

    def _label(m: dict) -> str:
        return f"{m.get('name', '')} {m.get('details', {}).get('family', '')}"

    usable = [m for m in installed if not _EXCLUDE_RE.search(_label(m))] or installed
    within = [m for m in usable if _size_b(m) <= _SIZE_CEILING_B]
    if within:
        # largest plain model first; a reasoning model only when nothing else fits
        return max(
            within,
            key=lambda m: (not _REASONING_RE.search(_label(m)), _size_b(m)),
        )["name"]
    # everything is over the ceiling: smallest one, still preferring plain chat
    return min(
        usable,
        key=lambda m: (bool(_REASONING_RE.search(_label(m))), _size_b(m)),
    )["name"]


def active_model() -> str | None:
    """The model the app will use. For Gemini (cloud) that is simply the
    configured Gemini model when a key is present. Otherwise the Ollama model
    auto-selected from what's installed (or CASEMIND_LLM_MODEL when set). None
    when no model is available. Cached briefly since the status bar polls often."""
    if LLM_PROVIDER == "gemini":
        return GEMINI_MODEL if GEMINI_API_KEY else None

    now = time.monotonic()
    if now - float(_model_cache["ts"]) < _MODEL_TTL:
        return _model_cache["model"]  # type: ignore[return-value]
    try:
        model = _pick_model(_installed_models())
    except Exception:
        model = None
    _model_cache["ts"] = now
    _model_cache["model"] = model
    return model


def ollama_available() -> bool:
    return active_model() is not None


# A whole WhatsApp export is far past any local model's context window, so long
# text is translated in pieces and stitched back together. Sized to stay well
# inside an 8B model's context while keeping the number of round-trips sane.
TRANSLATE_CHUNK_CHARS = 2500


def _split_for_translation(text: str, limit: int = TRANSLATE_CHUNK_CHARS) -> list[str]:
    """Split on line boundaries into <=limit-char pieces, so a chat transcript
    is never cut mid-message. A single over-long line is passed through whole
    (the model truncates it, which beats dropping it silently)."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if current and size + len(line) > limit:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line)
    if current:
        chunks.append("".join(current))
    return chunks


def translate(text: str, target: str = "Hebrew") -> str | None:
    """Translate free text into `target` (default Hebrew) with the local LLM —
    for reading Russian/other-language evidence. Personal and place names are
    transliterated into the target script. Long documents are translated in
    chunks and rejoined. Returns the translation, "" for empty input, or None
    when the LLM is unavailable/fails on the first chunk."""
    text = (text or "").strip()
    if not text:
        return ""

    system = {
        "role": "system",
        "content": (
            f"You are a professional legal translator. Translate the user's "
            f"text into {target}. Output ONLY the translation — no notes, no "
            f"transliteration in brackets, no original text. Render personal "
            f"and place names in {target} script. Keep line breaks, timestamps, "
            f"phone numbers and speaker names in place."
        ),
    }

    pieces: list[str] = []
    for i, chunk in enumerate(_split_for_translation(text)):
        out = translate_chunk(chunk, target)
        if out is None:
            if i == 0:
                return None  # LLM unavailable — caller falls back to an error
            # partial failure mid-document: keep what we have, flag the gap
            # rather than throwing away minutes of completed translation
            logger.warning("translation failed on chunk %s of a long document", i)
            pieces.append("[…קטע שלא תורגם…]")
            continue
        pieces.append(out)
    return "\n".join(pieces)


def translate_chunk(chunk: str, target: str = "Hebrew") -> str | None:
    """One chunk, one LLM call. Exposed so the background worker can save
    progress after each piece instead of losing hours of work on a restart."""
    return _chat([
        {
            "role": "system",
            "content": (
                f"You are a professional legal translator. Translate the user's "
                f"text into {target}. Output ONLY the translation — no notes, no "
                f"transliteration in brackets, no original text. Render personal "
                f"and place names in {target} script. Keep line breaks, timestamps, "
                f"phone numbers and speaker names in place."
            ),
        },
        {"role": "user", "content": chunk},
    ])


# The background worker uses small pieces on purpose. Ollama serves one request
# at a time, so whatever the worker has in flight is exactly how long a user can
# be stuck waiting. At ~14 chars/sec a 2500-char chunk stalls them for ~3
# minutes; 700 keeps the worst case under a minute. On-demand translation, where
# the user is already waiting, keeps the larger chunks (fewer round-trips).
BACKGROUND_CHUNK_CHARS = int(os.getenv("CASEMIND_BG_CHUNK_CHARS", "700"))


def split_for_translation(text: str) -> list[str]:
    return _split_for_translation(text, limit=BACKGROUND_CHUNK_CHARS)


def to_hebrew_name(name: str) -> str | None:
    """Hebrew form of a personal name (e.g. Юлия → יוליה) so a Russian name can
    be shown with its Hebrew reading. None if the LLM is unavailable/fails."""
    name = (name or "").strip()
    if not name:
        return ""
    out = _chat([
        {
            "role": "system",
            "content": (
                "Transliterate the personal name into Hebrew letters. "
                "Output ONLY the Hebrew name — no punctuation, no explanation, "
                "no Latin/Cyrillic."
            ),
        },
        {"role": "user", "content": name},
    ])
    if not out:
        return out
    # models sometimes add quotes or a trailing note; keep the first line only
    return out.splitlines()[0].strip().strip('"\'').strip()


def synthesize_answer(question: str, citations: list[dict]) -> str | None:
    """Ask the local LLM to answer from the cited excerpts.

    Returns the answer text, or None when the LLM is unavailable/fails —
    callers must fall back to citation-only mode. Raises nothing."""
    excerpts = "\n\n".join(
        f"[{i}] (file: {c.get('filename')}, location: {c.get('source_location')})\n"
        f"{c.get('text', '')}"
        for i, c in enumerate(citations, 1)
    )
    # small models drift languages; be explicit, and last (recency wins)
    if HEBREW_RE.search(question):
        language_rule = "ענה בעברית בלבד. סיים כל משפט בסימון המקור שלו, למשל [1]."
    else:
        language_rule = (
            "Answer strictly in the language of the question. "
            "End every sentence with its source marker, e.g. [1]."
        )

    content = _chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Evidence excerpts:\n\n{excerpts}\n\n"
                f"Question: {question}\n\n{language_rule}"
            ),
        },
    ])
    if content is None:
        return None
    cleaned = _clean_answer(content, len(citations))
    # small models sometimes emit only citation markers ("[3]") with no prose;
    # that's not an answer — signal failure so the caller shows citations-only
    if not _has_prose(cleaned):
        return None
    return cleaned


_WORD_RE = re.compile(r"[^\W\d_]", re.UNICODE)  # any letter (incl. Hebrew), not digit/punct


def _has_prose(answer: str) -> bool:
    """True if the answer contains real words, not just citation markers /
    punctuation. Strip [n] markers first, then require at least one letter."""
    without_citations = re.sub(r"\[\d+\]", "", answer or "")
    return bool(_WORD_RE.search(without_citations))


# Ollama serves one request at a time per model. The background translator would
# otherwise hold it for hours, and a user's question would sit behind it — a
# trivial call measured 219s while the worker ran. So user-facing calls are
# counted, and the background worker waits for them to finish before starting
# its next piece.
_local = threading.local()
_interactive_count = 0
_idle = threading.Condition()


def is_background() -> bool:
    return getattr(_local, "background", False)


def mark_background() -> None:
    """Called by the background worker thread; its calls yield to the user."""
    _local.background = True


# Set on every user request (see main.py). The gate below is not enough on its
# own: Ollama runs one request at a time, so a chunk already in flight still
# blocks the user for its full duration. Keeping background chunks small bounds
# that stall, and standing down while the user is active means it happens at
# most once per session rather than on every question.
USER_IDLE_GRACE_SECONDS = float(os.getenv("CASEMIND_USER_IDLE_GRACE", "90"))
_last_user_activity = 0.0


def note_user_activity() -> None:
    global _last_user_activity
    _last_user_activity = time.monotonic()


def user_is_active() -> bool:
    return (time.monotonic() - _last_user_activity) < USER_IDLE_GRACE_SECONDS


def wait_until_user_idle(timeout: float = 300.0) -> None:
    """Block while a user-facing LLM call is in flight, or the user is actively
    using the app. Background work is never worth making a person wait."""
    with _idle:
        _idle.wait_for(lambda: _interactive_count == 0, timeout=timeout)
    deadline = time.monotonic() + timeout
    while user_is_active() and time.monotonic() < deadline:
        time.sleep(2)


def _chat(messages: list[dict]) -> str | None:
    model = active_model()
    if model is None:
        return None
    if is_background():
        return _chat_call(model, messages)

    global _interactive_count
    with _idle:
        _interactive_count += 1
    try:
        return _chat_call(model, messages)
    finally:
        with _idle:
            _interactive_count -= 1
            _idle.notify_all()


def _chat_call(model: str, messages: list[dict]) -> str | None:
    # one dispatch point for every LLM call. Default is local Ollama (evidence
    # never leaves the machine). Gemini is opt-in and sends the text to Google —
    # a privacy trade-off the user makes deliberately, for cloud speed.
    if LLM_PROVIDER == "gemini":
        return _gemini_call(messages)
    return _ollama_call(model, messages)


def _ollama_call(model: str, messages: list[dict]) -> str | None:
    payload = {
        "model": model,
        "stream": False,
        "messages": messages,
        "options": {"temperature": 0.1},
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SECONDS) as resp:
            body = json.load(resp)
        return (body.get("message", {}).get("content") or "").strip() or None
    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
        return None


def _gemini_call(messages: list[dict]) -> str | None:
    """Google Gemini via REST. Cloud — the text leaves the machine. Opt-in only.

    Same message shape as the Ollama path (system + user turns); Gemini wants the
    system turn as systemInstruction and the rest under contents.
    """
    if not GEMINI_API_KEY:
        logger.warning("Gemini selected but CASEMIND_GEMINI_API_KEY is not set")
        return None

    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [
        {"role": "user", "parts": [{"text": m["content"]}]}
        for m in messages if m["role"] != "system"
    ]
    payload: dict = {"contents": contents, "generationConfig": {"temperature": 0.1}}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SECONDS) as resp:
            body = json.load(resp)
        parts = body["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip() or None
    except Exception as exc:
        logger.warning("Gemini call failed: %s", exc)
        return None


CONTRADICTION_PROMPT = """You compare two evidence excerpts from a criminal case.
Decide if they CONTRADICT each other: incompatible factual claims about
events, people, places, times, or objects.

NOT contradictions: differences in file names, ID numbers, reference codes,
random markers, or formatting. Two documents merely describing different
things are CONSISTENT.

Reply with EXACTLY one line:
CONTRADICTION | <one short sentence explaining the conflict>
or
CONSISTENT"""


def judge_contradiction(text_a: str, text_b: str) -> dict | None:
    """Returns {'verdict': 'contradiction'|'consistent', 'explanation': str},
    or None when the LLM is unavailable/unparseable."""
    # explanation intentionally not language-pinned: the default 3B model
    # produces clean English but mixed-script Hebrew; larger models via
    # CASEMIND_LLM_MODEL improve this
    content = _chat([
        {"role": "system", "content": CONTRADICTION_PROMPT},
        {"role": "user", "content": f"Excerpt A:\n{text_a}\n\nExcerpt B:\n{text_b}"},
    ])
    if content is None:
        return None
    first_line = content.splitlines()[0].strip()
    upper = first_line.upper()
    if upper.startswith("CONTRADICTION"):
        explanation = first_line.split("|", 1)[1].strip() if "|" in first_line else ""
        return {"verdict": "contradiction", "explanation": explanation}
    if upper.startswith("CONSISTENT"):
        return {"verdict": "consistent", "explanation": ""}
    return None


def _clean_answer(answer: str, citation_count: int) -> str:
    """Normalize model artifacts: [_1] -> [1], grouped [1,2,3] -> [1][2][3],
    and drop citation indices past the provided excerpts (hallucinated)."""
    answer = re.sub(r"\[_+(\d+)\]", r"[\1]", answer)
    # latin junk glued to a leading Hebrew word (e.g. "_theנאשם")
    answer = re.sub(r"^[_a-zA-Z]{1,8}(?=[֐-׿])", "", answer)

    def _fix_group(match: re.Match) -> str:
        numbers = [n.strip() for n in match.group(1).split(",")]
        valid = [n for n in numbers if n.isdigit() and 1 <= int(n) <= citation_count]
        return "".join(f"[{n}]" for n in valid)

    answer = re.sub(r"\[(\d+(?:\s*,\s*\d+)*)\]", _fix_group, answer)
    return answer.strip()
