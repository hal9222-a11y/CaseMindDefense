from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem


class EvidenceTableWidget(QTableWidget):
    evidence_selected = Signal(dict)

    HEADERS = ["ID", "Filename", "Type", "Size", "Status", "Imported", "SHA256"]

    def __init__(self) -> None:
        super().__init__()

        self._items: list[dict[str, Any]] = []

        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        self.setRowCount(len(items))

        for row, item in enumerate(items):
            values = [
                str(item.get("id", "")),
                item.get("filename", ""),
                item.get("mime_type", ""),
                str(item.get("size_bytes", "")),
                item.get("status", ""),
                item.get("imported_at", ""),
                self._short_hash(item.get("sha256", "")),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.setItem(row, col, cell)

        self.resizeColumnsToContents()

    def _on_selection_changed(self) -> None:
        row = self.currentRow()
        if 0 <= row < len(self._items):
            self.evidence_selected.emit(self._items[row])

    @staticmethod
    def _short_hash(value: str) -> str:
        return f"{value[:16]}..." if value else ""
