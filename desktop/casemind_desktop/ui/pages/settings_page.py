from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from api.client import ApiClient
from config.settings import BACKEND_BASE_URL
from workers.api_worker import run_async


class SettingsPage(QWidget):
    """Connection info + evidence-integrity and backup actions."""

    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api

        title = QLabel("Settings")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")

        key_state = "configured" if os.getenv("CASEMIND_API_KEY") else "not set (open local mode)"
        info = QLabel(
            f"Backend: {BACKEND_BASE_URL}    ·    API key: {key_state}\n"
            "Set CASEMIND_API_KEY on both backend and desktop to require authentication."
        )
        info.setStyleSheet("color: #9CA3AF;")

        # which LLM is doing AI answers and translation, and how to switch it.
        # The status bar shows the live model; this explains the choice.
        provider = os.getenv("CASEMIND_LLM_PROVIDER", "ollama").lower()
        if provider == "gemini":
            llm_line = (
                "🤖 מנוע AI: <b>Gemini (ענן)</b> — מהיר, אך חומרי החקירה נשלחים "
                "לשרתי Google. לחזרה למקומי: הסר את CASEMIND_LLM_PROVIDER."
            )
        else:
            llm_line = (
                "🤖 מנוע AI: <b>מקומי (Ollama)</b> — חומרי החקירה לא יוצאים מהמחשב.<br>"
                "להאצת תרגום דרך הענן (Gemini): הגדר "
                "<code>CASEMIND_LLM_PROVIDER=gemini</code> ו-"
                "<code>CASEMIND_GEMINI_API_KEY=…</code> על השרת.<br>"
                "⚠️ שים לב: זה שולח את חומרי החקירה ל-Google. שקול היטב בתיק פלילי."
            )
        llm_info = QLabel(llm_line)
        llm_info.setWordWrap(True)
        llm_info.setTextFormat(Qt.RichText)
        llm_info.setStyleSheet("color: #9CA3AF; padding-top: 6px;")

        self.verify_button = QPushButton("Verify Evidence Integrity")
        self.backup_button = QPushButton("Create Backup")
        self.relocate_button = QPushButton("📁 שנה נתיב מקור החומר")
        self.verify_button.clicked.connect(self._verify)
        self.backup_button.clicked.connect(self._backup)
        self.relocate_button.clicked.connect(self._relocate_source)

        actions = QHBoxLayout()
        actions.addWidget(self.verify_button)
        actions.addWidget(self.backup_button)
        actions.addWidget(self.relocate_button)
        actions.addStretch()

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Action results will appear here.")

        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addWidget(info)
        layout.addWidget(llm_info)
        layout.addLayout(actions)
        layout.addWidget(self.output)
        self.setLayout(layout)

    def _set_busy(self, busy: bool) -> None:
        self.verify_button.setEnabled(not busy)
        self.backup_button.setEnabled(not busy)
        self.relocate_button.setEnabled(not busy)

    def _relocate_source(self) -> None:
        # the files already live in the app's local store; this only re-points
        # the RECORDED source folder after the user moved the originals
        try:
            info = self.api.source_root()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "שגיאה", str(exc))
            return
        old = info.get("root") or ""
        if not old:
            QMessageBox.information(self, "אין חומר", "לא נמצאו ראיות עם נתיב מקור.")
            return

        new = QFileDialog.getExistingDirectory(
            self, "בחר את התיקייה החדשה שאליה הועבר החומר", old)
        if not new:
            return
        if QMessageBox.question(
            self, "שינוי נתיב מקור",
            f"לעדכן את נתיב המקור של {info.get('count', 0)} ראיות?\n\n"
            f"מ:\n{old}\n\nאל:\n{new}\n\n"
            "הקבצים עצמם כבר שמורים מקומית — רק הרישום מתעדכן.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        self._set_busy(True)
        run_async(self.api.relocate_source, old, new,
                  on_done=self._on_relocated, on_error=self._on_failed)

    def _on_relocated(self, result: dict) -> None:
        self._set_busy(False)
        self.output.setPlainText(
            f"עודכן נתיב המקור של {result.get('updated', 0)} ראיות.\n"
            f"מ: {result.get('old')}\nאל: {result.get('new')}"
        )

    def _verify(self) -> None:
        self._set_busy(True)
        self.output.setPlainText("Re-hashing all stored evidence...")
        run_async(self.api.verify_evidence, on_done=self._on_verified, on_error=self._on_failed)

    def _on_verified(self, result: dict) -> None:
        self._set_busy(False)
        lines = [
            "✅ Integrity check passed" if result.get("ok") else "🔴 INTEGRITY PROBLEMS FOUND",
            f"Verified: {result.get('verified')}",
        ]
        for item in result.get("missing", []):
            lines.append(f"MISSING: #{item['id']} {item['filename']}")
        for item in result.get("tampered", []):
            lines.append(f"TAMPERED: #{item['id']} {item['filename']}")
        self.output.setPlainText("\n".join(lines))

    def _backup(self) -> None:
        self._set_busy(True)
        self.output.setPlainText("Creating backup (DB snapshot + evidence store)...")
        run_async(self.api.create_backup, on_done=self._on_backed_up, on_error=self._on_failed)

    def _on_backed_up(self, result: dict) -> None:
        self._set_busy(False)
        size_mb = (result.get("size_bytes") or 0) / (1024 * 1024)
        self.output.setPlainText(
            "✅ Backup created\n"
            f"Path: {result.get('path')}\n"
            f"Evidence files: {result.get('evidence_files')} · Size: {size_mb:.1f} MB\n\n"
            "Restore: unzip and place casemind_defense.db and evidence_store back."
        )

    def _on_failed(self, error: str) -> None:
        self._set_busy(False)
        self.output.setPlainText(f"🔴 Failed: {error}")
