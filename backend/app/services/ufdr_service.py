"""Cellebrite UFDR ingestion.

A .ufdr is a ZIP with a Cellebrite report inside: `report.xml` (the structured
model — Contacts, Chats, Parties) plus `chats/<app>_<number>/chat-*.txt`,
human-readable transcripts where every message carries the sender's PHONE
NUMBER and name.

Walking the *exported* folder instead drowns the case in 340k loose files
(mostly app icons and thumbnail cache). Reading the UFDR gives the opposite:
the conversations, already attributed to numbered, named people — exactly the
who-said-what-to-whom the analysis engine is built on. This turns one .ufdr
into many searchable chat documents, each with its participants (name + phone)
as first-class entities.

Attachments (voice notes, images) inside the UFDR are noted per message but not
yet transcribed here — that is a deliberate follow-up; the text is the bulk of
the value and the whole point is to stop importing the noise.
"""
from __future__ import annotations

import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

CHAT_TXT_RE = re.compile(r"chat-\d+\.txt$", re.I)
_MESSAGE_SEP = re.compile(r"-{10,}")
# Cellebrite writes "13/06/2021 20:53:08(UTC+3)"
_TS_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}(?::\d{2})?)")
# a participant line entry: "972528772478@s.whatsapp.net Юля"
_PARTY_RE = re.compile(r"(\+?\d[\d]{6,}@\S+|\+?\d[\d\-\s]{6,}\d)\s*(.*)")


def is_ufdr(path: Path) -> bool:
    """A Cellebrite report: a zip whose root holds report.xml. Cheap to check —
    only the central directory is read, not the whole archive."""
    if path.suffix.lower() != ".ufdr":
        return False
    try:
        with zipfile.ZipFile(path) as z:
            return "report.xml" in z.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


_SYSTEM_BODIES = (
    "messages and calls are end-to-end encrypted",
    "הודעות ושיחות מוצפנות",
    "changed the subject",
    "changed this group's",
    "created group",
)


def _is_system_body(body: str) -> bool:
    low = (body or "").lower()
    return any(marker in low for marker in _SYSTEM_BODIES)


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _clean_phone(raw: str) -> str:
    """The account id before '@' if present, else the digit run. WhatsApp ids
    look like 972528772478@s.whatsapp.net — the number is the interesting part."""
    account = raw.split("@", 1)[0]
    digits = _digits(account)
    return digits or _digits(raw)


def _local(tag: str) -> str:
    """localname of a (possibly namespaced) tag."""
    return tag.rsplit("}", 1)[-1]


def _contact_from_model(model) -> tuple[str, list[str]]:
    name = ""
    numbers: list[str] = []
    for field in model.iter():
        # the Contact's OWN Name comes before its Photos; a ContactPhoto also has
        # a Name field (the .jpg filename) which must NOT clobber it — first only
        if _local(field.tag) == "field" and field.get("name") == "Name" and not name:
            name = "".join(field.itertext()).strip()
        # a real phone number is a PhoneNumber model's Value field — NOT the
        # digits inside a photo filename (972...-1413838454.jpg)
        if _local(field.tag) == "model" and field.get("type") == "PhoneNumber":
            for sub in field.iter():
                if _local(sub.tag) == "field" and sub.get("name") == "Value":
                    num = _digits("".join(sub.itertext()))
                    if len(num) >= 6:
                        numbers.append(num)
    return name, numbers


# a real phone report's report.xml runs to 1.8 GB (hundreds of thousands of
# Party/InstantMessage models). ET.fromstring loads the whole tree into memory
# and dies; iterparse STREAMS it, and we clear each finished model so memory
# stays flat. Contact/PhoneNumber subtrees are kept until the Contact ends (its
# numbers are nested children), everything else is freed on sight.
_KEEP_UNTIL_CONTACT = {"Contact", "PhoneNumber", "ContactPhoto"}


def parse_contacts(source) -> dict[str, str]:
    """phone(digits) -> best display name, from the report's Contact models.
    `source` is raw bytes or a file-like stream. Best-effort: a malformed or
    truncated report must not sink the whole import."""
    if isinstance(source, (bytes, bytearray)):
        import io

        source = io.BytesIO(source)

    contacts: dict[str, str] = {}
    try:
        for _event, elem in ET.iterparse(source, events=("end",)):
            if _local(elem.tag) != "model":
                continue
            mtype = elem.get("type")
            if mtype == "Contact":
                name, numbers = _contact_from_model(elem)
                for num in numbers:
                    if name and not contacts.get(num):
                        contacts[num] = name
                elem.clear()
            elif mtype not in _KEEP_UNTIL_CONTACT:
                elem.clear()  # free the Party/InstantMessage/etc. bulk
    except ET.ParseError:
        pass
    return contacts


def _parse_participants(header: str) -> dict[str, str]:
    """phone(digits) -> name from the 'Participants:' header line."""
    out: dict[str, str] = {}
    m = re.search(r"Participants:\s*(.+)", header)
    if not m:
        return out
    for entry in m.group(1).split(","):
        entry = entry.replace("(owner)", "").strip()
        pm = _PARTY_RE.match(entry)
        if pm:
            phone = _clean_phone(pm.group(1))
            name = pm.group(2).strip()
            if phone:
                out[phone] = name
    return out


def parse_chat(text: str) -> dict:
    """Parse one chat-*.txt into {participants, owner_phone, messages}.

    Each message: {sender, phone, timestamp, body, attachments, is_owner}.
    The owner is the phone whose messages are marked '(owner)'."""
    blocks = _MESSAGE_SEP.split(text)
    header = blocks[0] if blocks else ""
    participants = _parse_participants(header)

    # "(owner)" tags the device owner's participant entry — Cellebrite prints it
    # right after that entry (often wrapping to its own line). The last phone
    # token before "(owner)" is the owner.
    owner_phone = ""
    om = re.search(r"(\+?\d[\d]{5,}@\S+|\+?\d[\d\-\s]{5,}\d)[^\d@]*?\(owner\)", header, re.S)
    if om:
        owner_phone = _clean_phone(om.group(1))

    messages: list[dict] = []
    for block in blocks[1:]:
        if not block.strip():
            continue
        ts_m = _TS_RE.search(block)
        timestamp = ts_m.group(1) if ts_m else ""

        is_owner = bool(re.search(r"^\s*\(owner\)", block, re.M))
        sender_phone, sender_name = "", ""
        fm = re.search(r"^From:\s*(.+)$", block, re.M)
        if fm:
            pm = _PARTY_RE.match(fm.group(1).strip())
            if pm:
                sender_phone = _clean_phone(pm.group(1))
                sender_name = pm.group(2).strip()
            else:
                sender_name = fm.group(1).strip()
        elif is_owner:
            sender_phone = owner_phone
            sender_name = participants.get(owner_phone, "") or "בעל המכשיר"
        # a From line can read "<phone> Дима (owner)" — strip the tag so the owner
        # isn't a second graph node ("Дима" vs "Дима (owner)") the participants
        # header already strips it, this covers the message-line path too
        sender_name = re.sub(r"\s*\(owner\)\s*", "", sender_name).strip()

        attachments = re.findall(r"#\d+:\s*(\S+)", block)

        # Body: everything after the 'Body:' line to the block end
        body = ""
        bm = re.search(r"Body:\s*(.*)$", block, re.S)
        if bm:
            body = bm.group(1).strip()

        # WhatsApp's own system messages ("Messages and calls are end-to-end
        # encrypted…") are not something a person said — drop them so they
        # never become a speaker or a chunk
        if sender_name.startswith("System Message") or _is_system_body(body):
            continue

        if body or attachments:
            messages.append({
                "sender": sender_name or participants.get(sender_phone, "") or sender_phone,
                "phone": sender_phone,
                "timestamp": timestamp,
                "body": body,
                "attachments": attachments,
                "is_owner": is_owner,
            })

    return {"participants": participants, "owner_phone": owner_phone, "messages": messages}


def chat_to_chunks(chat: dict, chat_name: str, max_chars: int = 1200) -> list[dict]:
    """Normalized message chat -> chunk dicts (text/source_location/speakers),
    the exact shape index_evidence expects, so UFDR chats flow through the same
    entity/graph pipeline as WhatsApp exports. speakers carry name AND phone so
    resolution and phone-linking both fire."""
    messages = chat["messages"]
    if not messages:
        return []

    chunks: list[dict] = []
    current: list[str] = []
    speakers: set[str] = set()
    size = 0
    start = 0

    def flush(end: int) -> None:
        if not current:
            return
        chunks.append({
            "text": "\n".join(current),
            "source_location": f"{chat_name}:messages:{start + 1}-{end}",
            "speakers": sorted(speakers),
        })

    for index, msg in enumerate(messages):
        who = msg["sender"] or "?"
        line = f"{msg['timestamp']} - {who}: {msg['body']}".strip()
        if msg["attachments"]:
            line += f"  [{len(msg['attachments'])} קבצים מצורפים]"
        if current and size + len(line) > max_chars:
            flush(index)
            current, speakers, size, start = [], set(), 0, index
        current.append(line)
        # record the person by name (the graph node) — the phone rides along as
        # its own speaker token so a name<->phone edge forms in the same passage
        if msg["sender"]:
            speakers.add(msg["sender"])
        if msg["phone"]:
            speakers.add(f"+{msg['phone']}")
        size += len(line) + 1

    flush(len(messages))
    return chunks


def extract_ufdr(path: Path) -> dict:
    """Open a .ufdr and return {contacts, chats}. chats is a list of
    {name, participants, owner_phone, chunks} — one per conversation."""
    result: dict = {"contacts": {}, "chats": []}
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "report.xml" in names:
            try:
                # stream the report (it can be >1GB) instead of reading it whole
                with z.open("report.xml") as report:
                    result["contacts"] = parse_contacts(report)
            except Exception as exc:  # report parsing is best-effort
                logger.warning("UFDR contact parse failed for %s: %s", path.name, exc)

        for name in names:
            if not CHAT_TXT_RE.search(name):
                continue
            try:
                text = z.read(name).decode("utf-8", "ignore")
            except Exception as exc:
                logger.warning("UFDR chat read failed (%s): %s", name, exc)
                continue
            # a readable label: the conversation folder, e.g.
            # WhatsApp_972528772478@s.whatsapp.net
            label = Path(name).parent.name or name
            chat = parse_chat(text)
            chunks = chat_to_chunks(chat, label)
            if chunks:
                result["chats"].append({
                    "name": label,
                    "participants": chat["participants"],
                    "owner_phone": chat["owner_phone"],
                    "chunks": chunks,
                })
    return result
