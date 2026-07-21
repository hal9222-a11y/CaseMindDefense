"""Case-level AI insights: flags are deterministic/offline and cited; the
LLM-backed ones (summary, questions, events) fail closed with no LLM."""
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.db import get_engine
from app.services import case_analysis_service, event_service
from app.services.evidence_service import index_evidence


def _case_with_text(client, text: str) -> int:
    import tempfile
    from pathlib import Path

    case = client.post("/cases", json={"name": f"ins_{uuid.uuid4().hex[:8]}"}).json()
    p = Path(tempfile.mktemp(suffix=".txt"))
    p.write_text(text, encoding="utf-8")
    ev = client.post("/evidence/import-file",
                     json={"path": str(p), "case_id": case["id"]}).json()
    with Session(get_engine()) as s:
        index_evidence(s, ev["id"])
    return case["id"]


def test_flags_are_offline_deterministic_and_cited():
    with TestClient(app) as client:
        cid = _case_with_text(
            client,
            "13/06/2021 - Малой: перезвони, я оставил закладку. заплатить 5000 евро.\n"
            "13/06/2021 - Юля: у меня есть пистолет, берегись.",
        )
        out = client.get(f"/insights/flags?case_id={cid}").json()
        cats = out["summary"]["by_category"]
        assert cats.get("drugs") and cats.get("money") and cats.get("weapons")
        assert out["flags"], "flags must carry cited passages"
        first = out["flags"][0]
        assert first["evidence_id"] and first["snippet"] and first["terms"]
        client.delete(f"/cases/{cid}")


def test_llm_insights_fail_closed_without_llm():
    with TestClient(app) as client:
        cid = _case_with_text(client, "Встреча завтра. Давид приедет в десять.")
        with patch.object(case_analysis_service.llm_service, "ollama_available",
                          return_value=False):
            summ = client.get(f"/insights/case-summary?case_id={cid}").json()
            qs = client.get(f"/insights/questions?case_id={cid}").json()
        assert summ["overview"] is None and summ["reason"] == "no_llm"
        assert qs["questions"] == [] and qs["reason"] == "no_llm"
        with patch.object(event_service.llm_service, "ollama_available",
                          return_value=False):
            events = client.get(f"/insights/events?case_id={cid}").json()
        assert events == []
        client.delete(f"/cases/{cid}")


def test_event_json_parsing_is_defensive():
    # models wrap the array in prose / fences; keep only well-formed events
    raw = 'Вот события:\n```json\n[{"date":"13/06/2021","actors":["Малой","Юля"],' \
          '"action":"договорились о встрече"},{"action":""},{"bad":1}]\n```'
    events = event_service._parse_events(raw)
    assert len(events) == 1
    assert events[0]["actors"] == ["Малой", "Юля"]
    assert event_service._parse_events("no json here") == []
    assert event_service._parse_events(None) == []
