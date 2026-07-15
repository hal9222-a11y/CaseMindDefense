"""The cached NumPy search index must return the SAME ranking as a brute-force
cosine scan, and must refresh itself when chunks change."""
import uuid

import numpy as np
from sqlmodel import Session, select

from app.db import get_engine
from app.models.evidence import Evidence, EvidenceChunk
from app.services import search_index
from app.services.embedding_service import deserialize_embedding, embed_text, embedding_model_name


def _brute_force(session, query_vec, current_model, allowed, limit):
    q = np.asarray(query_vec, dtype=np.float32)
    scored = []
    for c in session.exec(select(EvidenceChunk)).all():
        if allowed is not None and c.evidence_id not in allowed:
            continue
        if (c.embedding_model or "") != current_model:
            continue
        v = deserialize_embedding(c.embedding or "")
        if len(v) != len(query_vec):
            continue
        s = float(np.asarray(v, dtype=np.float32) @ q)
        if s > 0:
            scored.append((s, c.id))
    scored.sort(reverse=True)
    return [cid for _s, cid in scored[:limit]]


def _seed_case(client) -> tuple[int, list[int]]:
    texts = [
        "Малой передал деньги возле банка в центре города",
        "Рина договорилась о встрече в кафе на набережной",
        "рецепт борща: свекла, капуста, картофель и мясо",
        "оплата 5000 евро наличными за товар",
    ]
    case = client.post("/cases", json={"name": f"idx_{uuid.uuid4().hex[:8]}"}).json()
    ids = []
    import tempfile
    from pathlib import Path
    from app.services.evidence_service import index_evidence
    for t in texts:
        p = Path(tempfile.mktemp(suffix=".txt"))
        p.write_text(t, encoding="utf-8")
        ev = client.post("/evidence/import-file",
                         json={"path": str(p), "case_id": case["id"]}).json()
        with Session(get_engine()) as s:
            index_evidence(s, ev["id"])
        ids.append(ev["id"])
    return case["id"], ids


def test_index_matches_brute_force_and_refreshes():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        case_id, ev_ids = _seed_case(client)
        with Session(get_engine()) as session:
            allowed = set(ev_ids)
            model = embedding_model_name()
            q = embed_text("кто платил деньги", kind="query")

            idx_hits = [h["chunk_id"] for h in
                        search_index.search(session, q, model, allowed, 3)]
            bf_hits = _brute_force(session, q, model, allowed, 3)
            assert idx_hits == bf_hits, f"index {idx_hits} != brute {bf_hits}"
            assert idx_hits, "should find money-related chunks"

        # add another evidence -> the signature changes -> index must refresh
        import tempfile
        from pathlib import Path
        from app.services.evidence_service import index_evidence
        p = Path(tempfile.mktemp(suffix=".txt"))
        p.write_text("новый перевод денег на счёт в Израиле", encoding="utf-8")
        ev = client.post("/evidence/import-file",
                         json={"path": str(p), "case_id": case_id}).json()
        with Session(get_engine()) as s:
            index_evidence(s, ev["id"])

        with Session(get_engine()) as session:
            allowed = set(ev_ids) | {ev["id"]}
            model = embedding_model_name()
            q = embed_text("перевод денег", kind="query")
            hits = search_index.search(session, q, model, allowed, 5)
            assert ev["id"] in {h["evidence_id"] for h in hits}, "new chunk not indexed"

        client.delete(f"/cases/{case_id}")


def test_scope_and_empty_query():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        case_id, ev_ids = _seed_case(client)
        with Session(get_engine()) as session:
            model = embedding_model_name()
            q = embed_text("деньги", kind="query")
            # scope to a single evidence -> only its chunks come back
            only = {ev_ids[0]}
            hits = search_index.search(session, q, model, only, 10)
            assert all(h["evidence_id"] in only for h in hits)
            # empty query vector -> nothing
            assert search_index.search(session, [], model, None, 5) == []
        client.delete(f"/cases/{case_id}")
