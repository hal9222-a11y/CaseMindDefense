from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem


class EvidenceTableWidget(QTableWidget):
    evidence_selected = Signal(dict)

    # SHA256 and full paths live in the Inspector; keep the table scannable
    HEADERS = ["ID", "Filename", "Type", "Size", "Status", "Imported"]

    def __init__(self) -> None:
        super().__init__()

        self._items: list[dict[str, Any]] = []

        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.itemSelectionChanged.connect(self._on_selection_changed)

        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Filename fills the width

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        self.setRowCount(len(items))

        for row, item in enumerate(items):
            values = [
                str(item.get("id", "")),
                item.get("filename", ""),
                (item.get("mime_type") or "").split("/")[-1],
                self._human_size(item.get("size_bytes") or 0),
                item.get("status", ""),
                (item.get("imported_at") or "")[:16].replace("T", " "),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.setItem(row, col, cell)

    def _on_selection_changed(self) -> None:
        row = self.currentRow()
        if 0 <= row < len(self._items):
            self.evidence_selected.emit(self._items[row])

    def select_by_id(self, evidence_id: int) -> bool:
        for row, item in enumerate(self._items):
            if item.get("id") == evidence_id:
                self.selectRow(row)
                return True
        return False

    @staticmethod
    def _human_size(size_bytes: int) -> str:
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        if size_bytes >= 1024:
            return f"{size_bytes / 1024:.0f} KB"
        return f"{size_bytes} B"
