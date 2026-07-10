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
- CITATIONS ARE MANDATORY: every sentence or bullet MUST end with the
  bracketed number of its source excerpt, like [1] or [2][3].
  Example: "הנאשם מכחיש את האישום [2]." An answer without [n] markers
  is invalid.
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
