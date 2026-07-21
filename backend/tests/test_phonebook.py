"""The phone directory turns the extracted contacts back into a number -> name(s)
lookup: formatting-independent, folding nickname/word-order variants, and
flagging a number saved under several different identities across devices."""
import uuid

from sqlmodel import Session

from app.db import get_engine, init_db
from app.models.evidence import Evidence, EvidenceChunk
from app.services.phonebook_service import lookup_phone, phone_directory


def _seed(session, case_id, chunks):
    ev = Evidence(
        original_path="x", stored_path="x", filename="Report.xml",
        sha256=uuid.uuid4().hex, size_bytes=1, status="indexed", case_id=case_id,
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    for i, (text, loc) in enumerate(chunks):
        session.add(EvidenceChunk(evidence_id=ev.id, chunk_index=i, text=text, source_location=loc))
    session.commit()
    return ev.id


def test_directory_folds_variants_and_flags_multi_identity():
    init_db()
    case = uuid.uuid4().int % 1_000_000
    with Session(get_engine()) as s:
        # device A phonebook: the number saved as "Nina Work"; device B as "Yulka"
        _seed(s, case, [
            ("אנשי קשר (מדריך המכשיר):\nנינה עבודה: +972542228282\nCharlie: +972526737908", "contacts"),
        ])
        _seed(s, case, [
            ("אנשי קשר (מדריך המכשיר):\nYulka Work: +972542228282\nWork Yulka: 0542228282", "contacts"),
        ])

        got = lookup_phone(s, case, "054-222-8282")  # formatting ignored
        assert got["phone"] == "542228282"
        names = {n["name"] for n in got["names"]}
        assert {"נינה עבודה", "Yulka Work", "Work Yulka"} <= names
        # "Yulka Work" and "Work Yulka" are one identity (word order); Nina is another
        assert got["distinct_identities"] == 2

        directory = phone_directory(s, case)
        top = directory[0]  # the multi-identity number sorts first
        assert top["phone"] == "542228282" and top["distinct_identities"] == 2
        # a call-log token is not a name
        assert lookup_phone(s, case, "0526737908")["primary_name"] == "Charlie"


def test_absent_number_reads_as_absent():
    init_db()
    with Session(get_engine()) as s:
        got = lookup_phone(s, uuid.uuid4().int % 1_000_000, "0500000000")
        assert got["names"] == [] and got["distinct_identities"] == 0
