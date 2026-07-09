from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from api.client import ApiClient
from workers.api_worker import run_async

IMAGE_MIME_PREFIX = "image/"
MAX_IMAGE_WIDTH = 900


class PreviewWidget(QWidget):
    """Preview engine: TXT via backend content API, images from the local
    evidence store, placeholder for PDF (real rendering in a later sprint)."""

    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api
        self._current_id: int | None = None
        self._highlight: str | None = None

        self._text_view = QTextEdit()
        self._text_view.setReadOnly(True)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        image_scroll = QScrollArea()
        image_scroll.setWidget(self._image_label)
        image_scroll.setWidgetResizable(True)

        self._message_label = QLabel("Select evidence to preview.")
        self._message_label.setAlignment(Qt.AlignCenter)
        self._message_label.setWordWrap(True)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._message_label)  # 0
        self._stack.addWidget(self._text_view)      # 1
        self._stack.addWidget(image_scroll)         # 2

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Preview"))
        layout.addWidget(self._stack)
        self.setLayout(layout)

    def show_evidence(self, item: dict[str, Any], highlight: str | None = None) -> None:
        self._current_id = item.get("id")
        self._highlight = highlight
        mime = item.get("mime_type") or ""

        if mime.startswith("text/"):
            self._show_message("Loading text preview...")
            run_async(
                self.api.get_evidence_content,
                item.get("id"),
                on_done=self._on_text_loaded,
                on_error=self._show_message,
            )
        elif mime.startswith(IMAGE_MIME_PREFIX):
            self._show_image(item)
        elif mime == "application/pdf":
            if highlight:
                # no PDF rendering yet, but the cited chunk itself is available
                self._text_view.setPlainText(
                    "[Cited excerpt — full PDF preview coming in a later sprint]\n\n"
                    f"{highlight}"
                )
                self._stack.setCurrentIndex(1)
                self._highlight = None
            else:
                self._show_message(
                    f"PDF preview is coming in a later sprint.\n\n{item.get('filename', '')}"
                )
        else:
            self._show_message(f"No preview available for type: {mime or 'unknown'}")

    def _on_text_loaded(self, payload: dict[str, Any]) -> None:
        if payload.get("id") != self._current_id:
            return  # a different row was selected while this request was in flight
        self._text_view.setPlainText(payload.get("text", ""))
        self._stack.setCurrentIndex(1)
        if self._highlight:
            # scroll to and select the cited chunk (first ~60 chars is enough
            # to locate it and keeps QTextEdit.find fast)
            self._text_view.moveCursor(QTextCursor.Start)
            self._text_view.find(self._highlight[:60].strip())
            self._highlight = None

    def _show_image(self, item: dict[str, Any]) -> None:
        stored = Path(item.get("stored_path", ""))
        if not stored.exists():
            self._show_message("Stored image file not found.")
            return
        pixmap = QPixmap(str(stored))
        if pixmap.isNull():
            self._show_message("Could not load image.")
            return
        if pixmap.width() > MAX_IMAGE_WIDTH:
            pixmap = pixmap.scaledToWidth(MAX_IMAGE_WIDTH, Qt.SmoothTransformation)
        self._image_label.setPixmap(pixmap)
        self._stack.setCurrentIndex(2)

    def _show_message(self, message: str) -> None:
        self._message_label.setText(message)
        self._stack.setCurrentIndex(0)
