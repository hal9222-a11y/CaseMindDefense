import re
from sqlmodel import Session, select
from app.models.evidence import EvidenceChunk

DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b")

def build_timeline(session: Session) -> list[dict]:
    events = []
    for chunk in session.exec(select(EvidenceChunk)).all():
        for d in DATE_RE.findall(chunk.text or ""):
            events.append({"date": d, "evidence_id": chunk.evidence_id, "chunk_index": chunk.chunk_index, "source_location": chunk.source_location, "text": chunk.text})
    return events
