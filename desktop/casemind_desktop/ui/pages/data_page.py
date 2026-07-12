from __future__ import annotations

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


class DataPage(QWidget):
    """Generic list page: title, refresh button, async-loaded table.
    Serves Timeline, Entities, and Contradictions."""

    def __init__(
        self,
        title: str,
        columns: list[tuple[str, str]],
        fetch_fn: Callable[[], list[dict[str, Any]]],
        note: str = "",
    ) -> None:
        super().__init__()

        self._fetch_fn = fetch_fn
        self._loaded_once = False

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
        self.table.set_rows(rows)

    def _on_failed(self, error: str) -> None:
        self.refresh_button.setEnabled(True)
        QMessageBox.critical(self, "Load Failed", error)
