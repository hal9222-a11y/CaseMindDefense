from __future__ import annotations

import re
from collections import Counter

# A WhatsApp export is structured, not prose:
#     6/3/21, 3:17 PM - Rina: Оки, жду
# Treating it as a text blob threw away the two things that matter most in an
# investigation: WHO said it, and to WHOM. The people who ARE the case — the
# conversation participants — were never extracted at all, while random
# capitalised words from the message bodies were.
MESSAGE_RE = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?)\s+-\s+"
    r"(?P<sender>[^:\n]{1,60}?):\s"
    r"(?P<body>.*)$"
)

# lines WhatsApp writes itself, not something a person said
SYSTEM_BODIES = (
    "messages and calls are end-to-end encrypted",
    "הודעות ושיחות מוצפנות",
    "created group",
    "changed the subject",
    "you were added",
)

MIN_MESSAGES_FOR_CHAT = 5  # below this it is prose that happens to look similar


def parse_messages(text: str) -> list[dict]:
    """Parse a WhatsApp export into messages. A message can span several lines;
    continuation lines belong to the message above them."""
    messages: list[dict] = []
    for line in (text or "").splitlines():
        match = MESSAGE_RE.match(line)
        if match:
            messages.append(
                {
                    "date": match.group("date"),
                    "time": match.group("time"),
                    "sender": match.group("sender").strip(),
                    "body": match.group("body").strip(),
                }
            )
        elif messages:
            messages[-1]["body"] += "\n" + line.strip()
    return messages


def is_chat_export(text: str) -> bool:
    return len(parse_messages(text)) >= MIN_MESSAGES_FOR_CHAT


def participants(messages: list[dict]) -> Counter:
    """Who is actually in this conversation, and how much each one talks.
    These are the people the case is about."""
    counts: Counter = Counter()
    for message in messages:
        sender = message["sender"]
        body = (message["body"] or "").lower()
        if any(marker in body for marker in SYSTEM_BODIES):
            continue
        counts[sender] += 1
    return counts


def chunk_by_messages(text: str, max_chars: int = 1200) -> list[dict]:
    """Chunk a chat on message boundaries instead of blind character offsets, so
    a citation never begins or ends mid-sentence of someone's message.

    Each chunk records who spoke in it, which is what lets the graph show who
    talks to whom.
    """
    messages = parse_messages(text)
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
        chunks.append(
            {
                "text": "\n".join(current),
                "source_location": f"messages:{start + 1}-{end}",
                "speakers": sorted(speakers),
            }
        )

    for index, message in enumerate(messages):
        line = f"{message['date']}, {message['time']} - {message['sender']}: {message['body']}"
        if current and size + len(line) > max_chars:
            flush(index)
            current, speakers, size, start = [], set(), 0, index
        current.append(line)
        speakers.add(message["sender"])
        size += len(line) + 1

    flush(len(messages))
    return chunks
