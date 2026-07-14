import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import get_engine
from app.main import app
from app.models.evidence import EvidenceChunk
from app.services import evidence_service


def test_evidence_is_never_invisible_while_being_reindexed(tmp_path, monkeypatch):
    """The old index used to be deleted BEFORE the slow work (OCR, embedding).
    For as long as that took — minutes — the evidence had zero chunks and was
    invisible to search, the timeline and the AI. A lawyer searching in that
    window is told the material is not in the case. That is the same lie as a
    search that invents evidence, pointing the other way.
    """
    marker = uuid.uuid4().hex
    with TestClient(app) as client:
        p = tmp_path / f"doc_{marker}.txt"
        p.write_text(f"The witness saw a white vehicle. {marker}", encoding="utf-8")
        ev_id = client.post("/evidence/import-file", json={"path": str(p)}).json()["id"]

        def chunk_count() -> int:
            with Session(get_engine()) as session:
                return len(
                    session.exec(
                        select(EvidenceChunk).where(EvidenceChunk.evidence_id == ev_id)
                    ).all()
                )

        assert chunk_count() > 0
        seen_during_reindex = []

        # embedding is the slow step; peek at what a concurrent search would see
        real_embed = evidence_service.embed_text

        def slow_embed(text, **kwargs):
            seen_during_reindex.append(chunk_count())
            return real_embed(text, **kwargs)

        monkeypatch.setattr(evidence_service, "embed_text", slow_embed)

        with Session(get_engine()) as session:
            evidence_service.index_evidence(session, ev_id)

        assert seen_during_reindex, "the slow step never ran"
        assert all(n > 0 for n in seen_during_reindex), (
            f"evidence had zero chunks mid-reindex: {seen_during_reindex}"
        )
        assert chunk_count() > 0
