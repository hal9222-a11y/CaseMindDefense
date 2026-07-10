from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from api.client import ApiClient
from workers.api_worker import run_async


class EvidenceController(QObject):
    """Mediates between evidence UI and the backend API; all calls are async."""

    evidence_loaded = Signal(list)
    load_failed = Signal(str)
    import_done = Signal(dict)
    import_failed = Signal(str)

    def __init__(self, api: ApiClient | None = None) -> None:
        super().__init__()
        self.api = api or ApiClient()

    def load_evidence(self, case_id: int | None = None) -> None:
        run_async(
            self.api.list_evidence,
            case_id,
            on_done=self.evidence_loaded.emit,
            on_error=self.load_failed.emit,
        )

    def import_file(self, file_path: str, case_id: int | None = None) -> None:
        run_async(
            self.api.import_evidence_file,
            file_path,
            case_id,
            on_done=self.import_done.emit,
            on_error=self.import_failed.emit,
        )
