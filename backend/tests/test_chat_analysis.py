import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services.chat_service import (
    chunk_by_messages,
    is_chat_export,
    parse_messages,
    participants,
)
from app.services.entity_service import extract_phones

CHAT = """6/3/21, 3:17 PM - Rina: Оки, жду
6/3/21, 3:55 PM - 4UDA privet: Хорошо
6/3/21, 3:55 PM - Rina: Я тебе привезу сама телефоны
6/7/21, 12:00 PM - Rina: Привет, позвони Юле: 054-991-2233
6/7/21, 12:01 PM - 4UDA privet: Ок, я передам Марине
6/7/21, 12:02 PM - Rina: Юля сказала что Алиса тоже придёт
"""


def test_a_chat_is_parsed_into_messages():
    messages = parse_messages(CHAT)
    assert len(messages) == 6
    assert messages[0]["sender"] == "Rina"
    assert messages[0]["body"] == "Оки, жду"
    assert is_chat_export(CHAT)


def test_the_participants_are_identified():
    # THE core failure: Rina (17,008 messages) and 4UDA privet (1,496) — the
    # people the case is actually about — were never extracted at all
    who = participants(parse_messages(CHAT))
    assert set(who) == {"Rina", "4UDA privet"}
    assert who["Rina"] == 4


def test_chunks_record_who_spoke_and_never_cut_a_message():
    chunks = chunk_by_messages(CHAT, max_chars=120)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk["speakers"]
        for line in chunk["text"].splitlines():
            # a chunk boundary must fall between messages, not inside one
            assert " - " in line and ": " in line
        assert chunk["source_location"].startswith("messages:")


def test_prose_is_not_mistaken_for_a_chat():
    assert not is_chat_export("העד מסר כי ראה רכב לבן ליד הבית בשעה 22:00.")


def test_phones_are_validated_and_international():
    text = "Israeli 054-991-2233, Russian +7 985 775-04-60, junk 20210705, id 123456789"
    found = extract_phones(text)
    assert "+972549912233" in found          # normalised to E.164
    assert "+79857750460" in found           # a Russian number the old regex could not see
    assert not any(p.startswith("+97220210705") for p in found)  # a date is not a phone


def test_a_phone_is_not_also_reported_as_a_vehicle_plate():
    # the ID/plate patterns are just runs of digits, so "052-465-7474" was also
    # yielding the "plate" 465-7474
    from app.services.ner_service import extract_entities

    found = extract_entities("טלפון 054-991-2233. רכב 12-345-67.")
    plates = [e["text"] for e in found if e["label"] == "vehicle_plate"]
    assert "12-345-67" in plates
    assert not any("2233" in p for p in plates)


def test_conversation_participants_become_people_in_the_evidence(tmp_path):
    with TestClient(app) as client:
        marker = uuid.uuid4().hex
        p = tmp_path / f"chat_{marker}.txt"
        p.write_text(CHAT + f"6/7/21, 12:03 PM - Rina: ref {marker}\n", encoding="utf-8")
        ev = client.post("/evidence/import-file", json={"path": str(p)}).json()

        entities = client.get("/entities", params={"limit": 1000}).json()
        people = {e["entity"] for e in entities if e["type"] == "person"}
        assert {"Rina", "4UDA privet"} <= people, "the chat participants must be people"

        # and the citation points at messages, not at a byte offset
        content = client.get(f"/evidence/{ev['id']}").json()
        assert content["status"] == "indexed"
