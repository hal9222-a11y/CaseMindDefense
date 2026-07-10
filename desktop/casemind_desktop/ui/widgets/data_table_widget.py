from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem


class DataTableWidget(QTableWidget):
    """Read-only table over a list of dicts. Double-click emits row_activated."""

    row_activated = Signal(dict)

    def __init__(self, columns: list[tuple[str, str]]) -> None:
        """columns: list of (header, dict_key)."""
        super().__init__()

        self._columns = columns
        self._rows: list[dict[str, Any]] = []

        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels([header for header, _ in columns])
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cellDoubleClicked.connect(self._on_double_clicked)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.setRowCount(len(rows))

        for row_index, row in enumerate(rows):
            for col_index, (_, key) in enumerate(self._columns):
                value = row.get(key, "")
                cell = QTableWidgetItem("" if value is None else str(value))
                cell.setToolTip(cell.text())
                self.setItem(row_index, col_index, cell)

        self.resizeColumnsToContents()

    def _on_double_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._rows):
            self.row_activated.emit(self._rows[row])
