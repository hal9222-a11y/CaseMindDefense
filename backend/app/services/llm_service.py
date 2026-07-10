from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("CASEMIND_OLLAMA_URL", "http://127.0.0.1:11434")
LLM_MODEL = os.getenv("CASEMIND_LLM_MODEL", "qwen2.5:3b-instruct")
LLM_TIMEOUT_SECONDS = int(os.getenv("CASEMIND_LLM_TIMEOUT", "120"))

SYSTEM_PROMPT = """You are an evidence analysis assistant for a criminal defense team.
You will receive numbered evidence excerpts and a question.

Hard rules:
- Answer ONLY from the evidence excerpts. Never use outside knowledge.
- Every sentence must end with its citation marker, e.g. [1] or [2][3].
- If the evidence does not answer the question, reply exactly: NOT_FOUND
- Be concise and factual. No speculation."""

HEBREW_RE = re.compile("[֐-׿]")


def ollama_available() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as resp:
            models = json.load(resp).get("models", [])
        return any(m.get("name", "").startswith(LLM_MODEL.split(":")[0]) for m in models)
    except Exception:
        return False


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
        language_rule = "ענה בעברית בלבד. אל תשתמש בשום שפה אחרת."
    else:
        language_rule = "Answer strictly in the language of the question."

    payload = {
        "model": LLM_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Evidence excerpts:\n\n{excerpts}\n\n"
                    f"Question: {question}\n\n{language_rule}"
                ),
            },
        ],
        "options": {"temperature": 0.1},
    }
    content = _chat(payload["messages"])
    if content is None:
        return None
    return _clean_answer(content, len(citations)) or None


def _chat(messages: list[dict]) -> str | None:
    payload = {
        "model": LLM_MODEL,
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
    """Normalize small-model artifacts: [_1] -> [1], drop citation markers
    that point past the provided excerpts (hallucinated indices)."""
    answer = re.sub(r"\[_+(\d+)\]", r"[\1]", answer)
    # latin junk glued to a leading Hebrew word (e.g. "_theנאשם")
    answer = re.sub(r"^[_a-zA-Z]{1,8}(?=[֐-׿])", "", answer)
    answer = re.sub(
        r"\[(\d+)\]",
        lambda m: m.group(0) if 1 <= int(m.group(1)) <= citation_count else "",
        answer,
    )
    return answer.strip()
