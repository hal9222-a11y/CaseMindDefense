import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services.timeline_service import _detect_order, _normalize_date


def test_document_with_a_day_above_12_is_month_first():
    # a WhatsApp export written 11/21/21 can only be month/day
    assert _detect_order(["11/1/18", "11/21/21", "6/3/21"]) == "month_first"


def test_document_with_a_first_part_above_12_is_day_first():
    assert _detect_order(["21/11/21", "11/1/18"]) == "day_first"


def test_fully_ambiguous_document_falls_back_to_day_first():
    assert _detect_order(["11/1/18", "6/3/21"]) == "day_first"


def test_the_whole_document_uses_one_convention():
    # the bug: 11/21/21 forced month/day for itself, while 11/1/18 was read as
    # day/month in the SAME file — 1 Nov became 11 Jan, ten months adrift
    order = _detect_order(["11/1/18", "11/21/21"])
    assert _normalize_date("11/1/18", order) == "2018-11-01"   # 1 Nov, not 11 Jan
    assert _normalize_date("11/21/21", order) == "2021-11-21"


def test_timeline_does_not_repeat_a_date_within_a_passage(tmp_path):
    # every chat line starts with the same date; the timeline used to emit one
    # row per occurrence, burying the page in duplicates of the same text
    marker = uuid.uuid4().hex
    chat = "\n".join(
        f"11/21/21, 7:2{i} PM - Rina: message number {i} {marker}" for i in range(9)
    )
    with TestClient(app) as client:
        p = tmp_path / f"chat_{marker}.txt"
        p.write_text(chat, encoding="utf-8")
        ev = client.post("/evidence/import-file", json={"path": str(p)}).json()

        rows = [
            e for e in client.get("/timeline").json()
            if e["evidence_id"] == ev["id"]
        ]
        assert rows, "the date should still appear"
        # 9 occurrences of 11/21/21 in one passage -> one row, not nine
        per_passage = [r for r in rows if r["normalized_date"] == "2021-11-21"]
        assert len(per_passage) == len({r["chunk_index"] for r in per_passage})
