"""Cellebrite UFDR ingestion: a .ufdr is a zip with report.xml + chat-*.txt.
Importing one must yield searchable conversations attributed to named, numbered
people — not a folder of loose noise."""
import uuid
import zipfile
from pathlib import Path

from app.services.ufdr_service import extract_ufdr, is_ufdr, parse_chat, parse_contacts

# a chat-*.txt in the exact Cellebrite grammar (owner tag, From, Timestamp,
# Attachments, Body; blocks split by a long dashed line)
CHAT_TXT = """﻿Start Time: 13/06/2021 20:51:33(UTC+3)
Last Activity: 19/11/2021 18:17:45(UTC+2)
Participants: 972528772478@s.whatsapp.net Юля, 972545642339@s.whatsapp.net Малой
(owner)
-----------------------------
From: System Message System Message
Timestamp: 13/06/2021 20:51:33(UTC+3)
Source App: WhatsApp
Body:
Messages and calls are end-to-end encrypted.
-----------------------------
From: 972528772478@s.whatsapp.net Юля
Timestamp: 13/06/2021 20:55:00(UTC+3)
Source App: WhatsApp
Body:
Привет, ты дома?
-----------------------------
(owner)
Timestamp: 13/06/2021 21:06:44(UTC+3)
Source App: WhatsApp
Attachments:
#1: chats\\WhatsApp_972528772478@s.whatsapp.net\\attachments1\\a49c6.jpg
Body:
Да, перезвони мне на 052-465-7474
-----------------------------
"""

REPORT_XML = """<?xml version="1.0" encoding="utf-8"?>
<project xmlns="http://x">
  <model type="Contact">
    <field name="Name"><value type="String"><![CDATA[Алекс Голованов]]></value></field>
    <multiModelField name="Photos" type="ContactPhoto">
      <model type="ContactPhoto"><field name="Name"><value><![CDATA[972-1359.jpg]]></value></field></model>
    </multiModelField>
    <multiModelField name="Entries" type="PhoneNumber">
      <model type="PhoneNumber"><field name="Value"><value type="String"><![CDATA[972522506596]]></value></field></model>
    </multiModelField>
  </model>
</project>"""


def _make_ufdr(tmp_path: Path) -> Path:
    p = tmp_path / f"report_{uuid.uuid4().hex[:8]}.ufdr"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("report.xml", REPORT_XML)
        z.writestr("chats/WhatsApp_972528772478@s.whatsapp.net/chat-1.txt", CHAT_TXT)
    return p


def test_is_ufdr_detects_zip_with_report(tmp_path):
    good = _make_ufdr(tmp_path)
    assert is_ufdr(good)
    plain = tmp_path / "note.ufdr"
    plain.write_text("not a zip", encoding="utf-8")
    assert not is_ufdr(plain)


def test_parse_chat_attributes_messages_to_named_numbered_people():
    chat = parse_chat(CHAT_TXT)
    assert chat["participants"]["972528772478"] == "Юля"
    assert chat["owner_phone"] == "972545642339"  # the (owner) tag follows Малой

    bodies = [m["body"] for m in chat["messages"]]
    # the encryption system message is dropped, the two real messages kept
    assert not any("end-to-end encrypted" in b for b in bodies)
    assert any("ты дома" in b for b in bodies)

    owner_msg = next(m for m in chat["messages"] if m["is_owner"])
    assert owner_msg["sender"] == "Малой"       # owner resolved to the name
    assert owner_msg["phone"] == "972545642339"
    assert owner_msg["attachments"]             # the .jpg is recorded


def test_parse_contacts_uses_real_name_not_photo_filename():
    contacts = parse_contacts(REPORT_XML.encode("utf-8"))
    assert contacts.get("972522506596") == "Алекс Голованов"
    # the digits inside the photo filename must NOT become a contact
    assert "9721359" not in contacts


def test_parse_contacts_streams_large_reports():
    # a real report.xml is >1GB: hundreds of thousands of Party/InstantMessage
    # models around the Contacts. The streaming parser must free that bulk while
    # still capturing every Contact (freeing a Contact's PhoneNumber child early
    # would drop its number).
    import io

    bulk = "".join(
        f'<model type="InstantMessage" id="m{i}"><field name="Body">'
        f'<value>msg {i}</value></field></model>' for i in range(5000)
    )
    contact = (
        '<model type="Contact"><field name="Name"><value><![CDATA[Дима]]></value></field>'
        '<multiModelField name="Entries" type="PhoneNumber">'
        '<model type="PhoneNumber"><field name="Value"><value>972501112233</value></field></model>'
        "</multiModelField></model>"
    )
    xml = f'<project>{bulk}{contact}{bulk}</project>'.encode("utf-8")
    contacts = parse_contacts(io.BytesIO(xml))
    assert contacts.get("972501112233") == "Дима"


def test_extract_and_index_end_to_end(tmp_path):
    from fastapi.testclient import TestClient
    from sqlmodel import Session, select

    from app.main import app
    from app.db import get_engine
    from app.models.evidence import EvidenceChunk, ExtractedEntity
    from app.services.evidence_service import index_evidence

    ufdr = _make_ufdr(tmp_path)
    data = extract_ufdr(ufdr)
    assert data["chats"] and data["contacts"]

    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"ufdr_{uuid.uuid4().hex[:8]}"}).json()
        ev = client.post(
            "/evidence/import-file", json={"path": str(ufdr), "case_id": case["id"]}
        ).json()
        with Session(get_engine()) as session:
            index_evidence(session, ev["id"])
            chunks = session.exec(
                select(EvidenceChunk).where(EvidenceChunk.evidence_id == ev["id"])
            ).all()
            entities = session.exec(
                select(ExtractedEntity).where(ExtractedEntity.evidence_id == ev["id"])
            ).all()

        texts = "\n".join(c.text for c in chunks)
        assert "ты дома" in texts                      # the conversation is searchable
        assert "אנשי קשר" in texts                      # the contacts directory too
        people = {e.text for e in entities if e.label == "person"}
        assert "Малой" in people or "Юля" in people    # participants became people
        phones = {e.text for e in entities if e.label == "phone"}
        assert any("7474" in p for p in phones)        # phone in a body was extracted

        client.delete(f"/cases/{case['id']}")
