from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """When CASEMIND_API_KEY is set, every request (except /health) must
    carry it in X-API-Key. Unset = open localhost dev mode.

    Read per-request (not cached) so tests and key rotation work without
    a restart; the comparison is constant-time."""
    expected = os.getenv("CASEMIND_API_KEY")
    if not expected:
        return
    # compare bytes: compare_digest raises TypeError on non-ASCII str,
    # which would turn a bad key into a 500 instead of a 401
    if not x_api_key or not secrets.compare_digest(
        x_api_key.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="invalid or missing API key")
