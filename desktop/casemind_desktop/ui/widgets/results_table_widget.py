from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem


class ResultsTableWidget(QTableWidget):
    """Search results / AI citations table. Emits result_selected for
    citation navigation (wired up in sprint 0.12.2)."""

    result_selected = Signal(dict)

    HEADERS = ["Filename", "Score", "Evidence ID", "Chunk", "Source", "Text"]

    def __init__(self) -> None:
        super().__init__()

        self._results: list[dict[str, Any]] = []

        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def set_results(self, results: list[dict[str, Any]]) -> None:
        self._results = results
        self.setRowCount(len(results))

        for row, item in enumerate(results):
            values = [
                item.get("filename", "") or "",
                str(item.get("score", "")),
                str(item.get("evidence_id", "")),
                str(item.get("chunk_index", "")),
                item.get("source_location", "") or "",
                item.get("text", "") or "",
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.setItem(row, col, cell)

        self.resizeColumnsToContents()

    def _on_selection_changed(self) -> None:
        row = self.currentRow()
        if 0 <= row < len(self._results):
            self.result_selected.emit(self._results[row])
