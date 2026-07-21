"""Sensitive-content flagging: surface the passages an investigator most needs
to find first — money, drugs, weapons, threats — across the whole case, each
with a citation.

Deliberately lexicon-based and OFFLINE, not an LLM scan. Two reasons: it must
run over tens of thousands of chunks in seconds (an 8B model reading each one
takes days), and a flag has to be explainable in court — "matched the term X at
this location" is defensible; "the AI felt it was suspicious" is not. The LLM's
role in understanding the case is summary/inference (see the other services);
flagging is retrieval, and retrieval should be exact.

Terms cover Hebrew, Russian and English because the evidence does."""
from __future__ import annotations

import re

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk

# category -> terms (lowercased matching). Word-boundary matched so "arm" does
# not fire on "alarm". Tuned for a Hebrew/Russian/English trafficking-adjacent
# case; extend per case via CASEMIND — the categories are the stable part.
FLAG_LEXICON: dict[str, list[str]] = {
    "money": [
        # Hebrew
        "כסף", "מזומן", "תשלום", "שילם", "לשלם", "העברה", "חוב", "אלף שקל", "יורו", "דולר",
        # Russian
        "деньг", "оплат", "заплат", "перевод", "наличн", "долг", "евро", "доллар",
        # English
        "cash", "payment", "transfer", "paid", "euro", "dollar",
    ],
    "drugs": [
        "סמים", "קוקאין", "חשיש", "גראס", "כדורים", "מנה",
        "наркот", "кокаин", "гашиш", "закладк", "товар", "доза",
        "cocaine", "hashish", "weed", "pills", "dose",
    ],
    "weapons": [
        "אקדח", "נשק", "רובה", "כדורים", "סכין", "רימון",
        "оруж", "пистолет", "ствол", "патрон",
        "gun", "weapon", "pistol", "knife", "ammo",
    ],
    "threats": [
        "איום", "אהרוג", "להרוג", "לפגוע", "תיזהר", "אשבור", "נקמה",
        "убью", "убить", "убил", "угроз", "отомщу", "берегись",
        "kill", "threat", "hurt you", "revenge",
    ],
    "sex_work": [
        "עיסוי", "שירות", "לקוח", "פגישה", "מלון",
        "массаж", "услуг", "клиент", "интим",
        "massage", "escort", "client",
    ],
}

# match at a WORD START, allowing any suffix: Russian inflects heavily
# (закладка/закладку/закладки, заплатить/заплатил) and English conjugates
# (kill/killed), so anchoring only the front catches the family while
# (?<!\w) still stops mid-word hits (skill won't fire "kill").
# ponytail: front-anchor only, misses Hebrew prefixed forms (הכסף) and can
# over-match a longer word sharing a stem (нож→ножницы); upgrade to a stemmer
# or a curated morphology list per language if precision matters.
def _compile(terms: list[str]) -> re.Pattern:
    parts = sorted((re.escape(t) for t in terms), key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")", re.IGNORECASE)


_PATTERNS = {cat: _compile(terms) for cat, terms in FLAG_LEXICON.items()}
SNIPPET_RADIUS = 90


def _snippet(text: str, start: int, end: int) -> str:
    left = max(0, start - SNIPPET_RADIUS)
    right = min(len(text), end + SNIPPET_RADIUS)
    return ("…" if left else "") + text[left:right] + ("…" if right < len(text) else "")


def scan_flags(
    session: Session, case_id: int | None = None, categories: list[str] | None = None
) -> list[dict]:
    """Every passage that matches a sensitive category, with the matched term
    and a citation. One flag per (chunk, category) — the strongest snippet —
    so a chunk full of 'money' terms is one row, not fifty."""
    from app.services.scope import case_evidence_ids

    allowed = case_evidence_ids(session, case_id)
    wanted = {c for c in (categories or FLAG_LEXICON)} & set(_PATTERNS)

    filenames = {
        eid: fn for eid, fn in session.exec(select(Evidence.id, Evidence.filename)).all()
    }

    flags: list[dict] = []
    for chunk in session.exec(select(EvidenceChunk)).all():
        if allowed is not None and chunk.evidence_id not in allowed:
            continue
        text = chunk.text or ""
        if not text:
            continue
        for category in wanted:
            matches = list(_PATTERNS[category].finditer(text))
            if not matches:
                continue
            terms = sorted({m.group(0).lower() for m in matches})
            first = matches[0]
            flags.append({
                "category": category,
                "evidence_id": chunk.evidence_id,
                "filename": filenames.get(chunk.evidence_id),
                "chunk_index": chunk.chunk_index,
                "source_location": chunk.source_location,
                "terms": terms,
                "hits": len(matches),
                "snippet": _snippet(text, first.start(), first.end()),
            })

    # busiest passages first, grouped by category weight (more distinct terms =
    # more likely genuinely about the topic)
    flags.sort(key=lambda f: (-len(f["terms"]), -f["hits"]))
    return flags


def flag_summary(session: Session, case_id: int | None = None) -> dict:
    """Counts per category — the case's risk profile at a glance."""
    flags = scan_flags(session, case_id)
    counts: dict[str, int] = {}
    for f in flags:
        counts[f["category"]] = counts.get(f["category"], 0) + 1
    return {"total": len(flags), "by_category": counts}
