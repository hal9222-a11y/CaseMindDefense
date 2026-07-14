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

        total = s.get("evidence_total", 0)
        parts = []
        if s.get("busy"):
            n = s.get("processing", 0)
            current = s.get("current") or {}
            name = current.get("filename")
            stage = current.get("stage", "עיבוד")
            done = total - n
            if name:
                # what's being worked on now + progress through the backlog
                parts.append(f"⚙️ {stage}: {name}  ·  {done}/{total} — נותרו {n}")
            else:
                parts.append(f"⚙️ מעבד ברקע…  {done}/{total}")
        else:
            # the backlog is finished — say so, and say how it turned out
            parts.append(f"✅ סיים לעבד את כל החומר ({total} ראיות)")

        parts.append(f"📄 {s.get('indexed', 0)} עם טקסט")
        if s.get("no_text"):
            parts.append(f"🚫 {s['no_text']} ללא טקסט")
        failed = s.get("failed", 0)
        if failed:
            # never hide failures behind a green light
            parts.append(f"⚠️ {failed} נכשלו")

        if s.get("llm_available"):
            parts.append(f"🤖 AI זמין ({s.get('llm_model', '')})")
        else:
            parts.append("📄 AI לא זמין — מצב ציטוטים בלבד")

        self.showMessage("   ·   ".join(parts))
