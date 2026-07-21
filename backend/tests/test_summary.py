"""Evidence summarization: grounded on the item's own chunks, graceful when no
LLM, and it always returns the item's people (cheap, exact) as a header."""
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import summary_service


def test_no_llm_returns_people_but_no_summary(tmp_path):
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"sum_{uuid.uuid4().hex[:8]}"}).json()
        p = tmp_path / "doc.txt"
        p.write_text("Встреча с Давидом завтра. Позвони 052-465-7474.", encoding="utf-8")
        ev = client.post("/evidence/import-file",
                         json={"path": str(p), "case_id": case["id"]}).json()
        from app.db import get_engine
        from app.services.evidence_service import index_evidence
        from sqlmodel import Session
        with Session(get_engine()) as s:
            index_evidence(s, ev["id"])

        with patch.object(summary_service.llm_service, "ollama_available", return_value=False):
            out = client.post(f"/evidence/{ev['id']}/summarize").json()
        assert out["summary"] is None and out["reason"] == "no_llm"
        assert out["chunk_count"] >= 1
        client.delete(f"/cases/{case['id']}")


def test_summary_uses_only_this_items_text():
    # _sample_text keeps both ends of a long item within budget
    texts = ["HEAD" * 500, "MID" * 1000, "TAILEND" * 200]
    out = summary_service._sample_text(texts, 1000)
    assert out.startswith("HEAD") and out.rstrip().endswith("TAILEND")
    assert len(out) < len("".join(texts))
