from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from api.client import ApiClient
from ui.widgets.results_table_widget import ResultsTableWidget
from workers.api_worker import run_async


class AIPage(QWidget):
    def __init__(self, api: ApiClient | None = None) -> None:
        super().__init__()

        self.api = api or ApiClient()

        self.question_input = QTextEdit()
        self.question_input.setPlaceholderText("Ask a citation-based evidence question...")
        self.question_input.setMaximumHeight(90)

        self.ask_button = QPushButton("Ask")
        self.ask_button.clicked.connect(self.ask)

        self.answer_output = QTextEdit()
        self.answer_output.setReadOnly(True)
        self.answer_output.setPlaceholderText("The evidence-grounded answer will appear here.")

        self.citations = ResultsTableWidget()

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.ask_button)
        top_bar.addStretch()

        answer_panel = QWidget()
        answer_layout = QVBoxLayout()
        answer_layout.addWidget(QLabel("Answer"))
        answer_layout.addWidget(self.answer_output)
        answer_panel.setLayout(answer_layout)

        citations_panel = QWidget()
        citations_layout = QVBoxLayout()
        citations_layout.addWidget(QLabel("Citations"))
        citations_layout.addWidget(self.citations)
        citations_panel.setLayout(citations_layout)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(answer_panel)
        splitter.addWidget(citations_panel)
        splitter.setSizes([300, 300])

        layout = QVBoxLayout()
        layout.addWidget(self.question_input)
        layout.addLayout(top_bar)
        layout.addWidget(splitter)
        self.setLayout(layout)

    def ask(self) -> None:
        question = self.question_input.toPlainText().strip()
        if not question:
            return

        self.ask_button.setEnabled(False)
        self.answer_output.clear()
        self.answer_output.setPlaceholderText("Searching evidence...")
        self.citations.set_results([])
        run_async(
            self.api.ask_ai,
            question,
            on_done=self._on_answer,
            on_error=self._on_failed,
        )

    def _on_answer(self, result: dict) -> None:
        self.ask_button.setEnabled(True)
        self.answer_output.setPlainText(result.get("answer", ""))
        self.citations.set_results(result.get("citations", []))

    def _on_failed(self, error: str) -> None:
        self.ask_button.setEnabled(True)
        QMessageBox.critical(self, "AI Ask Failed", error)
