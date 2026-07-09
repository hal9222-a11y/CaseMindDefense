from __future__ import annotations

from typing import Any

from api.client import ApiClient


class EvidenceController:
    def __init__(self, api: ApiClient | None = None) -> None:
        self.api = api or ApiClient()

    def list_evidence(self) -> list[dict[str, Any]]:
        return self.api.list_evidence()

    def import_file(self, file_path: str) -> dict[str, Any]:
        return self.api.import_evidence_file(file_path)
