from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from api.client import ApiClient


class SearchPage(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.api = ApiClient()

        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Search evidence semantically...")

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.run_search)

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.query_input)
        top_bar.addWidget(self.search_button)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Filename", "Score", "Evidence ID", "Chunk", "Source", "Text"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        layout = QVBoxLayout()
        layout.addLayout(top_bar)
        layout.addWidget(self.table)

        self.setLayout(layout)

    def run_search(self) -> None:
        query = self.query_input.text().strip()
        if not query:
            return

        try:
            results = self.api.semantic_search(query)
            self.table.setRowCount(len(results))

            for row, item in enumerate(results):
                values = [
                    item.get("filename", ""),
                    f'{item.get("score", "")}',
                    str(item.get("evidence_id", "")),
                    str(item.get("chunk_index", "")),
                    item.get("source_location", ""),
                    item.get("text", ""),
                ]
                for col, value in enumerate(values):
                    self.table.setItem(row, col, QTableWidgetItem(value))

            self.table.resizeColumnsToContents()

        except Exception as exc:
            QMessageBox.critical(self, "Search Failed", str(exc))
