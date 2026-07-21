"""Ask for a person or a number and get what it is connected to.

This is the investigator move — "who is 0542228282, and who is around them" —
done by the machine: take a seed (a name or a phone), find every passage it
appears in, and surface the OTHER people and numbers that share those passages,
ranked by how often they co-occur. Phone seeds are enriched through the phone
directory (a number's aliases become part of the seed), so a search for one
number also pulls the conversations where it is written under a different name.

Read-only and grounded: every connection carries the evidence it was read from.
ponytail: co-occurrence at the chunk level over the case's extracted entities —
no LLM, deterministic. It finds who sits together in the text, not the semantics
of the tie; pair with /persons/suggest-relations for the labelled relationship.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from sqlmodel import Session, select

from app.models.evidence import Evidence, EvidenceChunk, ExtractedEntity
from app.services.phonebook_service import _cluster, _harvest, _norm_phone

_PERSON = ("person", "name")


def _digits(s: str) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


def _seed_is_phone(seed: str) -> bool:
    d = _digits(seed)
    return len(d) >= 6 and len(d) >= len(seed.replace(" ", "").replace("-", "").replace("+", "")) - 1


def _case_chunk_ids(session: Session, case_id: int) -> set[int]:
    return set(session.exec(
        select(Evidence.id).where(Evidence.case_id == case_id)
    ).all())


def find_connections(session: Session, case_id: int, seed: str, limit: int = 25) -> dict:
    """{seed, aliases, people, phones, evidence}. `people`/`phones` are the
    entities that co-occur with the seed in the case's text, most-connected
    first; `evidence` are the passages the seed itself appears in."""
    seed = (seed or "").strip()
    if not seed:
        return {"seed": seed, "aliases": [], "people": [], "phones": [], "evidence": []}

    ev_ids = _case_chunk_ids(session, case_id)
    if not ev_ids:
        return {"seed": seed, "aliases": [], "people": [], "phones": [], "evidence": []}

    # Build the number->names phonebook ONCE and reuse it (for the seed's aliases
    # and for naming every connected phone); calling the directory per-phone
    # re-scanned the whole case each time.
    phonebook = _harvest(session, case_id)

    def names_of(phone9: str, top: int = 3) -> list[str]:
        return [g[0] for g in _cluster(phonebook.get(phone9, Counter()))][:top]

    # 1) resolve the seed's own written forms. A phone seed also drags in every
    #    name it is saved under (so co-occurrence follows the number, not a label).
    aliases: list[str] = []
    seed_digits = _norm_phone(seed) if _seed_is_phone(seed) else ""
    if seed_digits:
        aliases = [n for n, _ in phonebook.get(seed_digits, Counter()).most_common()]
    seed_terms = {seed.lower(), *(a.lower() for a in aliases)}

    # 2) locate the passages the seed appears in. Narrow in SQL FIRST — a phone by
    #    its contiguous digit core, a name by the string — so we load a handful of
    #    candidate chunks, not the whole case (that was ~30s/query and grows). A
    #    number written with separators ("054-222-8282") can slip past the core
    #    LIKE; that recall corner is worth the 30x speed for an interactive ask.
    like = f"%{seed_digits}%" if seed_digits else f"%{seed}%"
    rows = session.exec(
        select(EvidenceChunk.evidence_id, EvidenceChunk.chunk_index, EvidenceChunk.text)
        .where(EvidenceChunk.evidence_id.in_(ev_ids), EvidenceChunk.text.contains(seed if not seed_digits else seed_digits))
    ).all()
    seed_locs: set[tuple[int, int]] = set()
    text_by_loc: dict[tuple[int, int], str] = {}
    for ev_id, idx, text in rows:
        low = (text or "").lower()
        if seed_digits and seed_digits in _digits(text):
            seed_locs.add((ev_id, idx))
            text_by_loc[(ev_id, idx)] = text or ""
        elif any(t and t in low for t in seed_terms if not t.isdigit()):
            seed_locs.add((ev_id, idx))
            text_by_loc[(ev_id, idx)] = text or ""
    if not seed_locs:
        return {"seed": seed, "aliases": aliases, "people": [], "phones": [], "evidence": []}

    # 3) tally the OTHER entities sharing those passages
    people: Counter = Counter()
    phones: Counter = Counter()
    ent_rows = session.exec(
        select(ExtractedEntity.evidence_id, ExtractedEntity.chunk_index,
               ExtractedEntity.text, ExtractedEntity.label)
        .where(ExtractedEntity.evidence_id.in_({e for e, _ in seed_locs}))
    ).all()
    for ev_id, idx, text, label in ent_rows:
        if (ev_id, idx) not in seed_locs or not text:
            continue
        low = text.lower()
        if label in _PERSON:
            if low in seed_terms:
                continue  # the seed itself
            if seed_digits and _norm_phone(text) == seed_digits:
                continue  # the seed's own number, mis-labelled as a name
            people[text] += 1
        elif label == "phone":
            if seed_digits and _norm_phone(text) == seed_digits:
                continue
            phones[_norm_phone(text)] += 1

    # 4) name the connected phones from the phonebook built above
    phone_out = [
        {"phone": ph, "names": names_of(ph), "shared_passages": n}
        for ph, n in phones.most_common(limit)
    ]

    evidence = []
    for (ev_id, idx) in list(seed_locs)[:limit]:
        fn = session.get(Evidence, ev_id)
        snippet = text_by_loc[(ev_id, idx)]
        evidence.append({
            "evidence_id": ev_id,
            "filename": fn.filename if fn else None,
            "chunk_index": idx,
            "snippet": snippet[:300],
        })

    return {
        "seed": seed,
        "aliases": aliases,
        "people": [{"name": nm, "shared_passages": n} for nm, n in people.most_common(limit)],
        "phones": phone_out,
        "evidence": evidence,
    }
