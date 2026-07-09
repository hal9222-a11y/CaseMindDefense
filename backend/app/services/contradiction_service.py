from sqlmodel import Session, select
from app.models.evidence import EvidenceChunk

def find_contradictions(session: Session) -> list[dict]:
    chunks = session.exec(select(EvidenceChunk)).all()
    results = []
    for a in chunks:
        for b in chunks:
            if (a.id or 0) >= (b.id or 0):
                continue
            if "yes" in (a.text or "").lower() and "no" in (b.text or "").lower():
                results.append({"type": "simple_yes_no_conflict", "chunk_a": a.id, "chunk_b": b.id})
    return results
