"""Relation inference: for pairs of people the evidence keeps mentioning
together but nobody has labeled, ask the local LLM what the shared passages
actually say the relationship is. Output is a SUGGESTION with the passages it
was read from — never a stored fact; the user accepts it into a PersonLink or
ignores it. UNKNOWN answers are dropped, not guessed."""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.models.evidence import EvidenceChunk, Person, PersonLink
from app.services import llm_service
from app.services.knowledge_service import knowledge_graph

logger = logging.getLogger(__name__)

MAX_PAIRS = 8            # each pair is one LLM round-trip
PASSAGES_PER_PAIR = 2
PASSAGE_CHARS = 600

_PROMPT = (
    "לפניך קטעים מחומר ראיות שבהם מוזכרים יחד '{a}' ו-'{b}'.\n"
    "קבע מה הקשר ביניהם אך ורק לפי הקטעים. ענה בעברית ב-2-4 מילים "
    "(למשל: אחים, בני זוג, ספק-לקוח, חברים) ואחריהן נקודתיים והסבר של משפט אחד. "
    "אם הקטעים לא מלמדים על קשר — ענה בדיוק: UNKNOWN\n\n{passages}"
)


def suggest_relations(session: Session, case_id: int) -> list[dict]:
    """LLM-read relation suggestions for the strongest unlabeled person-person
    pairs in the knowledge graph. Empty list when no LLM is available — no
    heuristic fallback; a guessed relationship is worse than none."""
    if not llm_service.ollama_available():
        return []

    graph = knowledge_graph(session, case_id)
    persons = {p.id: p for p in session.exec(select(Person).where(Person.case_id == case_id)).all()}

    already: set[frozenset[int]] = set()
    if persons:
        for ln in session.exec(
            select(PersonLink).where(
                PersonLink.person_id.in_(list(persons)), PersonLink.kind == "relation"
            )
        ).all():
            if ln.related_person_id:
                already.add(frozenset((ln.person_id, ln.related_person_id)))

    def _pid(node_id: str) -> int | None:
        return int(node_id[2:]) if node_id.startswith("p:") else None

    candidates = []
    for edge in graph["edges"]:
        if edge["kind"] != "co_mention":
            continue
        a, b = _pid(edge["a"]), _pid(edge["b"])
        if a is None or b is None or frozenset((a, b)) in already:
            continue
        candidates.append((edge["weight"], a, b))
    candidates.sort(reverse=True)

    suggestions: list[dict] = []
    for _weight, a, b in candidates[:MAX_PAIRS]:
        name_a, name_b = persons[a].name, persons[b].name
        passages = _shared_passages(session, case_id, a, b, name_a, name_b)
        if not passages:
            continue
        prompt = _PROMPT.format(
            a=name_a, b=name_b,
            passages="\n---\n".join(p["text"][:PASSAGE_CHARS] for p in passages),
        )
        answer = llm_service.complete(prompt)
        if not answer or "UNKNOWN" in answer.upper():
            continue
        relation, _, rationale = answer.strip().partition(":")
        suggestions.append({
            "person_a_id": a, "person_a": name_a,
            "person_b_id": b, "person_b": name_b,
            "relation": relation.strip()[:60],
            "rationale": rationale.strip()[:300],
            "citations": [
                {"evidence_id": p["evidence_id"], "chunk_index": p["chunk_index"]}
                for p in passages
            ],
        })
    return suggestions


def _shared_passages(
    session: Session, case_id: int, a: int, b: int, name_a: str, name_b: str
) -> list[dict]:
    """Passages where both people appear under ANY of their written forms."""
    forms: dict[int, set[str]] = {a: {name_a}, b: {name_b}}
    for ln in session.exec(
        select(PersonLink).where(PersonLink.person_id.in_([a, b]), PersonLink.kind == "alias")
    ).all():
        forms[ln.person_id].add(ln.value)

    from app.models.evidence import Evidence

    found: list[dict] = []
    for chunk in session.exec(
        select(EvidenceChunk).where(
            EvidenceChunk.evidence_id.in_(select(Evidence.id).where(Evidence.case_id == case_id))
        )
    ).all():
        text = chunk.text or ""
        if any(f in text for f in forms[a]) and any(f in text for f in forms[b]):
            found.append({
                "evidence_id": chunk.evidence_id,
                "chunk_index": chunk.chunk_index,
                "text": text,
            })
            if len(found) >= PASSAGES_PER_PAIR:
                break
    return found
