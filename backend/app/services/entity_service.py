import re
from sqlmodel import Session, select
from app.models.evidence import EvidenceChunk

def list_entities(session: Session) -> list[dict]:
    counts = {}
    for chunk in session.exec(select(EvidenceChunk)).all():
        for entity in re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", chunk.text or ""):
            counts[entity] = counts.get(entity, 0) + 1
    return [{"entity": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
