from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from api.client import ApiClient
from ui.widgets.results_table_widget import ResultsTableWidget
from workers.api_worker import run_async


class SearchPage(QWidget):
    def __init__(self, api: ApiClient | None = None) -> None:
        super().__init__()

        self.api = api or ApiClient()

        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Search evidence...")
        self.query_input.returnPressed.connect(self.run_search)

        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["Semantic", "Keyword"])

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.run_search)

        self.results = ResultsTableWidget()

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.query_input)
        top_bar.addWidget(self.mode_selector)
        top_bar.addWidget(self.search_button)

        layout = QVBoxLayout()
        layout.addLayout(top_bar)
        layout.addWidget(self.results)
        self.setLayout(layout)

    def run_search(self) -> None:
        query = self.query_input.text().strip()
        if not query:
            return

        search_fn = (
            self.api.semantic_search
            if self.mode_selector.currentText() == "Semantic"
            else self.api.keyword_search
        )
        self.search_button.setEnabled(False)
        run_async(
            search_fn,
            query,
            on_done=self._on_results,
            on_error=self._on_failed,
        )

    def _on_results(self, results: list[dict]) -> None:
        self.search_button.setEnabled(True)
        self.results.set_results(results)

    def _on_failed(self, error: str) -> None:
        self.search_button.setEnabled(True)
        QMessageBox.critical(self, "Search Failed", error)
