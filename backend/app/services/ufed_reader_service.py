"""Cellebrite UFED *Reader* XML report ingestion — the folder-extraction format.

The physical / AdvancedLogical folder extractions ship a flat, human-readable
Report.xml that is NOT the Physical-Analyzer report a .ufdr holds: no
`<model type=>` models and no chats/<app>/chat-*.txt. Its structure is plain
sections:

    <reports><report>
        <contacts>
            <contact><name/><phone_number><value/></phone_number>...</contact>
        </contacts>
        <sms_message><number/><name/><timestamp/><type/><text/></sms_message>
        <mms_message>...</mms_message>
    </report></reports>

The ~13 folder-only devices (S20 Ultra, S10+, the iPhones, ...) have ONLY this —
their WhatsApp *chats* were never decoded (their voice notes are imported
separately, from the Audio/ folders). But the SMS/MMS text and the phone book
ARE here, and they are real evidence. This turns one Report.xml into
per-counterparty SMS conversations (the exact chunk shape index_evidence
expects) plus a contacts directory, so they flow through the entity / graph /
search pipeline just like a chat export.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from app.services.ufdr_service import _digits, _local, chat_to_chunks

logger = logging.getLogger(__name__)

OWNER = "בעל המכשיר"


def is_ufed_reader_report(path: Path) -> bool:
    """A UFED Reader export: an .xml whose root is <reports><report>. Cheap
    header sniff (first few KB only), so it can gate the ingest path without
    reading a 100+MB file."""
    if path.suffix.lower() != ".xml":
        return False
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096).decode("utf-8", "ignore").lower()
    except OSError:
        return False
    return "<reports>" in head and "<report" in head


def _child_text(elem, tag: str) -> str:
    """Text of the first DIRECT child named `tag` ('' if absent)."""
    for child in elem:
        if _local(child.tag) == tag:
            return "".join(child.itertext()).strip()
    return ""


def _contact_numbers(elem) -> tuple[str, list[str]]:
    name = _child_text(elem, "name")
    numbers: list[str] = []
    for child in elem:
        if _local(child.tag) == "phone_number":
            value = _digits(_child_text(child, "value"))
            if len(value) >= 6:  # a real number, not a stray digit run
                numbers.append(value)
    return name, numbers


def extract_ufed_reader(path: Path) -> dict:
    """{contacts: {phone: name}, chats: [{name, chunks}]}.

    SMS/MMS grouped by counterparty into per-thread conversations, sorted by
    time, plus the phone book. Streams the report (can be 100s of MB) with a
    defused iterparse and clears each finished element so memory stays flat;
    best-effort — a malformed or truncated report returns what parsed so far.
    """
    from xml.etree.ElementTree import ParseError

    from defusedxml.common import DefusedXmlException
    from defusedxml.ElementTree import iterparse as safe_iterparse

    contacts: dict[str, str] = {}
    threads: dict[str, list[dict]] = defaultdict(list)  # counterparty digits -> messages
    thread_name: dict[str, str] = {}

    try:
        for _event, elem in safe_iterparse(str(path), events=("end",)):
            tag = _local(elem.tag)
            if tag == "contact":
                name, numbers = _contact_numbers(elem)
                for num in numbers:
                    if name and not contacts.get(num):
                        contacts[num] = name
                elem.clear()
            elif tag in ("sms_message", "mms_message"):
                number = _digits(_child_text(elem, "number"))
                body = _child_text(elem, "text") or _child_text(elem, "body")
                if number and body:
                    name = _child_text(elem, "name")
                    named = name and name.upper() != "N/A"
                    outgoing = _child_text(elem, "type").lower() == "outgoing"
                    threads[number].append({
                        "sender": OWNER if outgoing else (name if named else number),
                        "phone": "" if outgoing else number,
                        "timestamp": _child_text(elem, "timestamp"),
                        "body": body,
                        "attachments": [],
                        "is_owner": outgoing,
                    })
                    if named and number not in thread_name:
                        thread_name[number] = name
                elem.clear()
    except (ParseError, DefusedXmlException, OSError) as exc:
        logger.warning("UFED Reader parse of %s ended early: %s", path.name, exc)

    chats: list[dict] = []
    for number, messages in threads.items():
        messages.sort(key=lambda m: m["timestamp"])  # ISO timestamps sort chronologically
        label = f"SMS_{thread_name.get(number, number)}"
        chunks = chat_to_chunks({"messages": messages}, label)
        if chunks:
            chats.append({"name": label, "chunks": chunks})
    return {"contacts": contacts, "chats": chats}
