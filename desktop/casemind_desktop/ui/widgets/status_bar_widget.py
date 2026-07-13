from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QStatusBar

from api.client import ApiClient
from workers.api_worker import run_async

POLL_MS = 4000  # how often to refresh the activity indicator


class StatusBarWidget(QStatusBar):
    """Live activity indicator: shows that the backend is up, whether the AI
    is ready, and what the system is doing right now (idle / processing N
    files). Polls /status so the user always knows the system is working."""

    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    def check_backend(self) -> None:
        self.showMessage("בודק חיבור לשרת…")
        self._poll()
        if not self._timer.isActive():
            self._timer.start(POLL_MS)

    def _poll(self) -> None:
        run_async(self.api.status, on_done=self._on_status)

    def _on_status(self, s: dict) -> None:
        if not s.get("ok"):
            self.showMessage(f"🔴 השרת אינו זמין — {s.get('error', '')}")
            return

        parts = []
        if s.get("busy"):
            n = s.get("processing", 0)
            parts.append(f"⚙️ מעבד {n} קבצים ברקע (OCR / תמלול / אינדוקס)…")
        else:
            parts.append("🟢 המערכת מוכנה")

        parts.append(f"{s.get('evidence_total', 0)} ראיות")

        if s.get("llm_available"):
            parts.append(f"🤖 AI זמין ({s.get('llm_model', '')})")
        else:
            parts.append("📄 AI לא זמין — מצב ציטוטים בלבד")

        self.showMessage("   ·   ".join(parts))
