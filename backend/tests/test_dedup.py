"""Content deduplication: the same chat imported as two formats has two
SHA256s, so it must be caught by CONTENT, not file bytes — and distinct
material must not be flagged."""
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.db import get_engine
from app.services.evidence_service import index_evidence

CHAT = (
    "6/3/21, 3:17 PM - Rina: приезжай завтра к десяти\n"
    "6/3/21, 3:20 PM - Малой: хорошо, буду\n"
    "6/3/21, 3:25 PM - Rina: не забудь деньги, 5000 евро\n"
    "6/3/21, 3:30 PM - Малой: помню, все привезу\n"
)
OTHER = (
    "1/1/22, 9:00 AM - David: meeting moved to Friday\n"
    "1/1/22, 9:05 AM - Sara: noted, I'll tell the team\n"
    "1/1/22, 9:10 AM - David: bring the contract please\n"
)


def _import(client, case_id, text, suffix, tmp_path):
    p = tmp_path / f"e_{uuid.uuid4().hex[:8]}{suffix}"
    p.write_text(text, encoding="utf-8")
    ev = client.post("/evidence/import-file",
                     json={"path": str(p), "case_id": case_id}).json()
    with Session(get_engine()) as s:
        index_evidence(s, ev["id"])
    return ev["id"]


def test_same_content_two_formats_is_one_group(tmp_path):
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"dup_{uuid.uuid4().hex[:8]}"}).json()
        cid = case["id"]
        # same chat text, two different files (different bytes/name/suffix)
        a = _import(client, cid, CHAT, ".txt", tmp_path)
        b = _import(client, cid, CHAT + "  ", ".txt", tmp_path)  # different bytes/name
        c = _import(client, cid, OTHER, ".txt", tmp_path)        # unrelated

        out = client.get(f"/insights/duplicates?case_id={cid}").json()
        assert out["count"] == 1, out
        group = out["groups"][0]
        ids = {m["id"] for m in group["members"]}
        assert ids == {a, b}          # the two copies, grouped
        assert c not in ids           # the unrelated chat is not
        assert group["reason"] == "exact"  # normalized text is identical
        client.delete(f"/cases/{cid}")


def test_distinct_material_yields_no_duplicates(tmp_path):
    with TestClient(app) as client:
        case = client.post("/cases", json={"name": f"nodup_{uuid.uuid4().hex[:8]}"}).json()
        cid = case["id"]
        _import(client, cid, CHAT, ".txt", tmp_path)
        _import(client, cid, OTHER, ".txt", tmp_path)
        out = client.get(f"/insights/duplicates?case_id={cid}").json()
        assert out["count"] == 0
        client.delete(f"/cases/{cid}")
