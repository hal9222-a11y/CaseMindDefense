from __future__ import annotations

from PySide6.QtWidgets import QStatusBar

from api.client import ApiClient
from workers.api_worker import run_async


class StatusBarWidget(QStatusBar):
    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api

    def check_backend(self) -> None:
        self.showMessage("Checking backend...")
        run_async(self.api.health, on_done=self._on_result)

    def _on_result(self, result: dict) -> None:
        if result.get("ok"):
            self.showMessage("🟢 Backend Connected")
        else:
            self.showMessage(f"🔴 Backend Offline - {result.get('error', '')}")
