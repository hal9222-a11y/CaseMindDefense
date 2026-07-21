from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem


class ResultsTableWidget(QTableWidget):
    """Search results / AI citations table. Double-clicking a row emits
    result_selected for citation navigation."""

    result_selected = Signal(dict)

    HEADERS = ["Filename", "Score", "Evidence ID", "Chunk", "Source", "Text"]

    def __init__(self) -> None:
        super().__init__()

        self._results: list[dict[str, Any]] = []

        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cellDoubleClicked.connect(self._on_double_clicked)

        header = self.horizontalHeader()
        # Interactive, NOT ResizeToContents — same O(rows²) freeze as the
        # evidence table once results run long. Text column stretches.
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(len(self.HEADERS) - 1, QHeaderView.Stretch)  # Text

    def set_results(self, results: list[dict[str, Any]]) -> None:
        self._results = results
        self.setUpdatesEnabled(False)  # batch: no repaint per cell
        sorting = self.isSortingEnabled()
        self.setSortingEnabled(False)
        try:
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
        finally:
            self.setSortingEnabled(sorting)
            self.setUpdatesEnabled(True)

    def _on_double_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._results):
            self.result_selected.emit(self._results[row])
