from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("CASEMIND_OLLAMA_URL", "http://127.0.0.1:11434")
LLM_TIMEOUT_SECONDS = int(os.getenv("CASEMIND_LLM_TIMEOUT", "120"))

# The app auto-selects the best general chat model actually installed in Ollama,
# so a machine with capable models uses them without configuration. Set
# CASEMIND_LLM_MODEL to force a specific model instead.
FORCED_MODEL = os.getenv("CASEMIND_LLM_MODEL") or None

# names/families that aren't general-purpose chat models — never auto-select
_EXCLUDE_RE = re.compile(r"ocr|embed|rerank|whisper|bge|vl|vision|code|guard|cloud", re.I)
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
        return next(
            (m["name"] for m in installed
             if m["name"] == FORCED_MODEL or m["name"].split(":")[0] == base),
            None,
        )
    def _label(m: dict) -> str:
        return f"{m.get('name', '')} {m.get('details', {}).get('family', '')}"

    usable = [m for m in installed if not _EXCLUDE_RE.search(_label(m))] or installed
    within = [m for m in usable if _size_b(m) <= _SIZE_CEILING_B]
    if within:
        return max(within, key=_size_b)["name"]
    return min(usable, key=_size_b)["name"]


def active_model() -> str | None:
    """The Ollama model the app will use, auto-selected from what's installed
    (or CASEMIND_LLM_MODEL when set). None when Ollama is down / has no model.
    Cached briefly since the status bar polls often."""
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
        out = _chat([system, {"role": "user", "content": chunk}])
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


def _chat(messages: list[dict]) -> str | None:
    model = active_model()
    if model is None:
        return None
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
