from __future__ import annotations

import os
from typing import Any

import requests

from api import endpoints
from config.settings import BACKEND_BASE_URL, REQUEST_TIMEOUT


class ApiClient:
    def __init__(self, base_url: str = BACKEND_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        api_key = os.getenv("CASEMIND_API_KEY")
        if api_key:
            self._session.headers["X-API-Key"] = api_key
        # the active case scope; analysis calls (search/timeline/entities/
        # contradictions/graph/ask) inherit it so one case's material never
        # bleeds into another's view. None = all cases.
        self.current_case_id: int | None = None

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _scoped(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.current_case_id is not None:
            params = {**params, "case_id": self.current_case_id}
        return params

    def health(self) -> dict[str, Any]:
        try:
            response = self._session.get(self._url(endpoints.HEALTH), timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return {"ok": True, "data": response.json() if response.content else {}}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def list_evidence(self, case_id: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if case_id is not None:
            params["case_id"] = case_id
        response = self._session.get(
            self._url(endpoints.EVIDENCE), params=params, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return response.json()

    def import_evidence_file(self, file_path: str, case_id: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"path": file_path}
        if case_id is not None:
            body["case_id"] = case_id
        response = self._session.post(
            self._url(endpoints.EVIDENCE_IMPORT_FILE),
            json=body,
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 409:
            detail = response.json().get("detail") or {}
            existing = detail.get("existing_id")
            raise RuntimeError(
                f"הקובץ הזה כבר קיים במערכת (ראיה מספר {existing}).\n"
                "זיהוי כפילויות לפי SHA256 — אותו קובץ לא ייקלט פעמיים."
            )
        response.raise_for_status()
        return response.json()

    def import_evidence_folder(self, folder_path: str, case_id: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"path": folder_path}
        if case_id is not None:
            body["case_id"] = case_id
        # registering a large folder (hashing every file) can take a while
        response = self._session.post(
            self._url(endpoints.EVIDENCE_IMPORT_FOLDER),
            json=body,
            timeout=600,
        )
        response.raise_for_status()
        return response.json()

    def delete_evidence(self, evidence_id: int) -> dict[str, Any]:
        response = self._session.delete(
            self._url(f"{endpoints.EVIDENCE}/{evidence_id}"),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def list_cases(self) -> list[dict[str, Any]]:
        response = self._session.get(self._url(endpoints.CASES), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def create_case(self, name: str) -> dict[str, Any]:
        response = self._session.post(
            self._url(endpoints.CASES), json={"name": name}, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return response.json()

    def generate_report(self, case_id: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if case_id is not None:
            body["case_id"] = case_id
        response = self._session.post(
            self._url(endpoints.REPORTS), json=body, timeout=60
        )
        response.raise_for_status()
        return response.json()

    def entity_graph(self, max_nodes: int = 30) -> dict[str, Any]:
        response = self._session.get(
            self._url(endpoints.ENTITY_GRAPH),
            params=self._scoped({"max_nodes": max_nodes}),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def get_evidence_content(self, evidence_id: int) -> dict[str, Any]:
        response = self._session.get(
            self._url(endpoints.evidence_content(evidence_id)),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def semantic_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        response = self._session.get(
            self._url(endpoints.SEMANTIC_SEARCH),
            params=self._scoped({"q": query, "limit": limit}),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def keyword_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        response = self._session.get(
            self._url(endpoints.SEARCH),
            params=self._scoped({"q": query, "limit": limit}),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def timeline(self, limit: int = 500) -> list[dict[str, Any]]:
        response = self._session.get(
            self._url(endpoints.TIMELINE),
            params=self._scoped({"limit": limit}),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def entities(self, limit: int = 500) -> list[dict[str, Any]]:
        response = self._session.get(
            self._url(endpoints.ENTITIES),
            params=self._scoped({"limit": limit}),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def contradictions(self) -> list[dict[str, Any]]:
        # LLM verdicts on candidate pairs take longer than normal calls
        response = self._session.get(
            self._url(endpoints.CONTRADICTIONS),
            params=self._scoped({}),
            timeout=180,
        )
        response.raise_for_status()
        return response.json()

    def verify_evidence(self) -> dict[str, Any]:
        response = self._session.post(
            self._url(endpoints.ADMIN_VERIFY), timeout=300
        )
        response.raise_for_status()
        return response.json()

    def create_backup(self) -> dict[str, Any]:
        response = self._session.post(
            self._url(endpoints.ADMIN_BACKUP), timeout=600
        )
        response.raise_for_status()
        return response.json()

    def ask_ai(self, question: str, limit: int = 5) -> dict[str, Any]:
        body: dict[str, Any] = {"question": question, "limit": limit}
        if self.current_case_id is not None:
            body["case_id"] = self.current_case_id
        response = self._session.post(
            self._url(endpoints.AI_ASK),
            json=body,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()