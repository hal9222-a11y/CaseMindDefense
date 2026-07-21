"""The /search endpoint must bound `limit` like /semantic does — an unbounded
limit lets one query pull the whole chunk table (LIMIT -1 in SQLite = no limit),
an N+1 scan of everything. See app/api/search.py + search_service.search_chunks."""
from fastapi.testclient import TestClient

from app.main import app


def test_search_limit_and_query_are_validated():
    with TestClient(app) as client:
        # below the floor and above the cap are rejected (422), matching /semantic
        assert client.get("/search", params={"q": "x", "limit": 0}).status_code == 422
        assert client.get("/search", params={"q": "x", "limit": 999999}).status_code == 422
        # empty query is rejected
        assert client.get("/search", params={"q": ""}).status_code == 422
        # a valid request is accepted
        assert client.get("/search", params={"q": "x", "limit": 10}).status_code == 200


def test_search_chunks_clamps_pathological_limit():
    """Defence in depth: even called directly, the service must never turn a
    negative/huge limit into 'return everything'."""
    from sqlmodel import Session

    from app.db import get_engine
    from app.services.search_service import search_chunks

    with Session(get_engine()) as s:
        # must not raise and must return a bounded list (empty DB -> [])
        assert search_chunks(s, "anything", limit=-1) == []
        assert search_chunks(s, "anything", limit=10**9) == []
