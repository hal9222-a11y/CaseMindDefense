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

    def status(self) -> dict[str, Any]:
        try:
            response = self._session.get(self._url("/status"), timeout=8)
            response.raise_for_status()
            return response.json()
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

    def delete_case(self, case_id: int) -> dict[str, Any]:
        response = self._session.delete(
            self._url(f"{endpoints.CASES}/{case_id}"), timeout=300
        )
        response.raise_for_status()
        return response.json()

    # --- persons ("who is who") ---
    def list_persons(self, case_id: int) -> list[dict[str, Any]]:
        response = self._session.get(
            self._url(endpoints.PERSONS), params={"case_id": case_id}, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return response.json()

    def create_person(self, case_id: int, name: str, description: str = "",
                      in_evidence: bool = True) -> dict[str, Any]:
        response = self._session.post(
            self._url(endpoints.PERSONS),
            json={"case_id": case_id, "name": name, "description": description,
                  "in_evidence": in_evidence},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def delete_person(self, person_id: int) -> dict[str, Any]:
        response = self._session.delete(
            self._url(f"{endpoints.PERSONS}/{person_id}"), timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return response.json()

    def add_person_link(self, person_id: int, kind: str, value: str = "",
                        evidence_id: int | None = None,
                        related_person_id: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"kind": kind, "value": value}
        if evidence_id is not None:
            body["evidence_id"] = evidence_id
        if related_person_id is not None:
            body["related_person_id"] = related_person_id
        response = self._session.post(
            self._url(f"{endpoints.PERSONS}/{person_id}/links"),
            json=body, timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def remove_person_link(self, person_id: int, link_id: int) -> dict[str, Any]:
        response = self._session.delete(
            self._url(f"{endpoints.PERSONS}/{person_id}/links/{link_id}"),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def suggest_phone_links(self, case_id: int) -> list[dict[str, Any]]:
        response = self._session.get(
            self._url(f"{endpoints.PERSONS}/suggest-phone-links"),
            params={"case_id": case_id}, timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def suggest_aliases(self, case_id: int) -> list[dict[str, Any]]:
        response = self._session.get(
            self._url(f"{endpoints.PERSONS}/suggest-aliases"),
            params={"case_id": case_id}, timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def translate_person_names(self, case_id: int) -> dict[str, Any]:
        # LLM-backed: transliterates each Cyrillic name, allow generous time
        response = self._session.post(
            self._url(f"{endpoints.PERSONS}/translate-names"),
            params={"case_id": case_id}, timeout=180,
        )
        response.raise_for_status()
        return response.json()

    def hebrew_names(self, names: list[str]) -> dict[str, Any]:
        # one LLM round-trip per name; the server caps the batch
        response = self._session.post(
            self._url(f"{endpoints.ENTITIES}/hebrew-names"),
            json={"names": names}, timeout=300,
        )
        response.raise_for_status()
        return response.json()

    def translate_text(self, text: str, target: str = "Hebrew") -> dict[str, Any]:
        # a local model manages ~10 chars/sec on real text and long documents are
        # done in chunks, so scale the wait with the text (generously) instead of
        # a flat ceiling that would abort a translation the server is still doing
        timeout = max(300, len(text) / 5)
        response = self._session.post(
            self._url("/translate"),
            json={"text": text, "target": target}, timeout=timeout,
        )
        if response.status_code == 413:
            raise RuntimeError(response.json().get("detail", "המסמך ארוך מדי לתרגום"))
        response.raise_for_status()
        return response.json()

    def person_graph(self, case_id: int) -> dict[str, Any]:
        response = self._session.get(
            self._url(f"{endpoints.PERSONS}/graph"),
            params={"case_id": case_id}, timeout=REQUEST_TIMEOUT,
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

    def entity_graph(
        self,
        max_nodes: int = 30,
        only_people: bool = True,
        min_edge_weight: int = 2,
        max_edges_per_node: int = 3,
    ) -> dict[str, Any]:
        response = self._session.get(
            self._url(endpoints.ENTITY_GRAPH),
            params=self._scoped({
                "max_nodes": max_nodes,
                "only_people": only_people,
                "min_edge_weight": min_edge_weight,
                "max_edges_per_node": max_edges_per_node,
            }),
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
        # the LLM synthesis (Ollama) runs up to the backend's 120s ceiling —
        # the default 15s gave up mid-generation; allow more than the backend
        response = self._session.post(
            self._url(endpoints.AI_ASK),
            json=body,
            timeout=180,
        )
        response.raise_for_status()
        return response.json()