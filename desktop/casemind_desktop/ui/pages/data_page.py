from __future__ import annotations

import re
from typing import Any, Callable

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.data_table_widget import DataTableWidget
from workers.api_worker import run_async

CYRILLIC_RE = re.compile("[Ѐ-ӿ]")
MAX_NAMES = 40  # matches the server cap: one LLM round-trip per name


class DataPage(QWidget):
    """Generic list page: title, refresh button, async-loaded table.
    Serves Timeline, Entities, and Contradictions."""

    def __init__(
        self,
        title: str,
        columns: list[tuple[str, str]],
        fetch_fn: Callable[[], list[dict[str, Any]]],
        note: str = "",
        hebrew_names_fn: Callable[[list[str]], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()

        self._fetch_fn = fetch_fn
        self._hebrew_names_fn = hebrew_names_fn
        self._loaded_once = False
        self._rows: list[dict[str, Any]] = []

        self.table = DataTableWidget(columns)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        top_bar = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        top_bar.addWidget(title_label)
        if note:
            note_label = QLabel(note)
            note_label.setStyleSheet("color: #9CA3AF;")
            top_bar.addWidget(note_label)
        top_bar.addStretch()

        # only the Entities page passes this: Russian names get a Hebrew reading
        self.hebrew_button: QPushButton | None = None
        if hebrew_names_fn is not None:
            self.hebrew_button = QPushButton("🇮🇱 עברית לשמות")
            self.hebrew_button.clicked.connect(self._translate_names)
            top_bar.addWidget(self.hebrew_button)

        top_bar.addWidget(self.refresh_button)

        layout = QVBoxLayout()
        layout.addLayout(top_bar)
        layout.addWidget(self.table)
        self.setLayout(layout)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        if not self._loaded_once:
            self._loaded_once = True
            self.refresh()

    def refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        run_async(self._fetch_fn, on_done=self._on_loaded, on_error=self._on_failed)

    def reset(self) -> None:
        """Drop cached rows and force a reload next time the page is shown
        (used when the case scope changes)."""
        self._loaded_once = False
        self.table.set_rows([])

    def _on_loaded(self, rows: list[dict[str, Any]]) -> None:
        self.refresh_button.setEnabled(True)
        self._rows = rows
        self.table.set_rows(rows)

    def _on_failed(self, error: str) -> None:
        self.refresh_button.setEnabled(True)
        QMessageBox.critical(self, "Load Failed", error)

    # --- Hebrew reading for Cyrillic names (Entities page only) ---
    def _translate_names(self) -> None:
        cyrillic = [
            r["entity"] for r in self._rows
            if CYRILLIC_RE.search(str(r.get("entity", ""))) and not r.get("hebrew")
        ][:MAX_NAMES]
        if not cyrillic:
            QMessageBox.information(
                self, "אין מה לתרגם",
                "לא נמצאו שמות ברוסית בטבלה (או שכולם כבר תורגמו).",
            )
            return
        self.hebrew_button.setEnabled(False)
        self.hebrew_button.setText("🇮🇱 מתרגם…")
        run_async(self._hebrew_names_fn, cyrillic,
                  on_done=self._on_names_translated, on_error=self._on_names_failed)

    def _on_names_translated(self, result: dict[str, Any]) -> None:
        self.hebrew_button.setEnabled(True)
        self.hebrew_button.setText("🇮🇱 עברית לשמות")
        names = result.get("names", {})
        for row in self._rows:
            hebrew = names.get(row.get("entity"))
            if hebrew:
                row["hebrew"] = hebrew
        self.table.set_rows(self._rows)
        QMessageBox.information(self, "סיום", f"תורגמו {len(names)} שמות לעברית.")

    def _on_names_failed(self, error: str) -> None:
        self.hebrew_button.setEnabled(True)
        self.hebrew_button.setText("🇮🇱 עברית לשמות")
        QMessageBox.critical(self, "שגיאת תרגום", error)
