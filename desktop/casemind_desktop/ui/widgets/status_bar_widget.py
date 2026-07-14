from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QStatusBar

from api.client import ApiClient
from backend_launcher import ensure_backend
from workers.api_worker import run_async

POLL_MS = 4000  # how often to refresh the activity indicator


class StatusBarWidget(QStatusBar):
    """Live activity indicator: shows that the backend is up, whether the AI
    is ready, and what the system is doing right now (idle / processing N
    files). Polls /status so the user always knows the system is working.

    It also brings the backend back if it dies. ensure_backend() only ran once,
    at launch, so a backend that died mid-session left the app throwing errors
    at the user until they restarted it themselves."""

    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api
        self._reviving = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    def check_backend(self) -> None:
        self.showMessage("בודק חיבור לשרת…")
        self._poll()
        if not self._timer.isActive():
            self._timer.start(POLL_MS)

    def _poll(self) -> None:
        run_async(self.api.status, on_done=self._on_status)

    def _revive_backend(self) -> None:
        """Restart the backend the moment it goes missing, rather than leaving
        the user to close and reopen the app. ensure_backend() is a no-op when
        the backend answers, so the only guard needed is against launching a
        second one while the first is still coming up."""
        if self._reviving:
            self.showMessage("🟠 השרת נפל — מפעיל אותו מחדש…")
            return
        self._reviving = True
        self.showMessage("🟠 השרת נפל — מפעיל אותו מחדש…")
        run_async(ensure_backend, on_done=self._on_revived, on_error=self._on_revive_failed)

    def _on_revived(self, started: bool) -> None:
        self._reviving = False
        if started:
            self._poll()  # show the real state immediately
        else:
            self.showMessage(
                "🔴 לא הצלחתי להפעיל את השרת מחדש — הפעל מחדש את האפליקציה."
            )

    def _on_revive_failed(self, error: str) -> None:
        self._reviving = False
        self.showMessage(f"🔴 השרת אינו זמין — {error}")

    def _on_status(self, s: dict) -> None:
        if not s.get("ok"):
            self._revive_backend()
            return
        self._reviving = False

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

        # the machine works ahead of the user: show the translation backlog
        pending = s.get("to_translate", 0)
        if pending:
            parts.append(f"🌐 מתרגם ברקע — נותרו {pending}")
        elif s.get("translated"):
            parts.append(f"🌐 {s['translated']} מתורגמים")

        if s.get("llm_available"):
            parts.append(f"🤖 AI זמין ({s.get('llm_model', '')})")
        else:
            parts.append("📄 AI לא זמין — מצב ציטוטים בלבד")

        self.showMessage("   ·   ".join(parts))
