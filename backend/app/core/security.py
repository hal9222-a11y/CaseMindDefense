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
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="invalid or missing API key")
