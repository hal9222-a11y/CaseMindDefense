from __future__ import annotations

from typing import Any

import requests

from api import endpoints
from config.settings import BACKEND_BASE_URL, REQUEST_TIMEOUT


class ApiClient:
    def __init__(self, base_url: str = BACKEND_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def health(self) -> dict[str, Any]:
        try:
            response = requests.get(self._url(endpoints.HEALTH), timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return {"ok": True, "data": response.json() if response.content else {}}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def list_evidence(self) -> list[dict[str, Any]]:
        response = requests.get(self._url(endpoints.EVIDENCE), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def import_evidence_file(self, file_path: str) -> dict[str, Any]:
        response = requests.post(
            self._url(endpoints.EVIDENCE_IMPORT_FILE),
            json={"path": file_path},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def get_evidence_content(self, evidence_id: int) -> dict[str, Any]:
        response = requests.get(
            self._url(endpoints.evidence_content(evidence_id)),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def semantic_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        response = requests.get(
            self._url(endpoints.SEMANTIC_SEARCH),
            params={"q": query, "limit": limit},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def keyword_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        response = requests.get(
            self._url(endpoints.SEARCH),
            params={"q": query, "limit": limit},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def timeline(self, limit: int = 500) -> list[dict[str, Any]]:
        response = requests.get(
            self._url(endpoints.TIMELINE),
            params={"limit": limit},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def entities(self, limit: int = 500) -> list[dict[str, Any]]:
        response = requests.get(
            self._url(endpoints.ENTITIES),
            params={"limit": limit},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def contradictions(self) -> list[dict[str, Any]]:
        # LLM verdicts on candidate pairs take longer than normal calls
        response = requests.get(
            self._url(endpoints.CONTRADICTIONS),
            timeout=180,
        )
        response.raise_for_status()
        return response.json()

    def ask_ai(self, question: str, limit: int = 5) -> dict[str, Any]:
        response = requests.post(
            self._url(endpoints.AI_ASK),
            json={"question": question, "limit": limit},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()