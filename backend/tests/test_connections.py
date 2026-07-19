"""find_connections: ask for a name or number, get the people and phones that
co-occur with it in the evidence, following a number through its aliases."""
import uuid

from sqlmodel import Session

from app.db import get_engine, init_db
from app.models.evidence import Evidence, EvidenceChunk, ExtractedEntity
from app.services.connections_service import find_connections


def _chunk(session, ev_id, idx, text, entities, loc=None):
    session.add(EvidenceChunk(evidence_id=ev_id, chunk_index=idx, text=text, source_location=loc or f"c{idx}"))
    for name, label in entities:
        session.add(ExtractedEntity(evidence_id=ev_id, chunk_index=idx, text=name, label=label))


def test_connections_follow_the_number_and_rank_co_occurrence():
    init_db()
    case = uuid.uuid4().int % 1_000_000
    with Session(get_engine()) as s:
        ev = Evidence(original_path="x", stored_path="x", filename="chat.txt",
                      sha256=uuid.uuid4().hex, size_bytes=1, status="indexed", case_id=case)
        s.add(ev); s.commit(); s.refresh(ev)
        # the phonebook: the number is saved as "Nina"
        _chunk(s, ev.id, 0, "אנשי קשר (מדריך המכשיר):\nנינה: +972542228282", [], loc="contacts")
        # a passage where the number appears with Chuda and a second number
        _chunk(s, ev.id, 1,
               "call 972542228282 -> Chuda and 972544715372",
               [("Chuda", "person"), ("972542228282", "phone"), ("972544715372", "phone")])
        # a passage with the number and Liza
        _chunk(s, ev.id, 2, "972542228282 talked to Liza",
               [("Liza", "person"), ("972542228282", "phone")])
        s.commit()

        r = find_connections(s, case, "0542228282")
        assert "נינה" in r["aliases"]                       # follows the number to its saved name
        people = {p["name"] for p in r["people"]}
        assert {"Chuda", "Liza"} <= people                  # co-occurring people surfaced
        assert "972542228282" not in people                 # the seed's own number excluded
        phones = {p["phone"] for p in r["phones"]}
        assert "544715372" in phones                         # the co-occurring number, normalized
        assert len(r["evidence"]) >= 2                       # cites the passages


def test_absent_seed_returns_empty():
    init_db()
    with Session(get_engine()) as s:
        r = find_connections(s, uuid.uuid4().int % 1_000_000, "Nobody")
        assert r["people"] == [] and r["phones"] == [] and r["evidence"] == []
