from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from api.client import ApiClient
from workers.api_worker import run_async


class AIPage(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.api = ApiClient()

        self.question_input = QTextEdit()
        self.question_input.setPlaceholderText("Ask a citation-based evidence question...")

        self.ask_button = QPushButton("Ask")
        self.ask_button.clicked.connect(self.ask)

        self.answer_output = QTextEdit()
        self.answer_output.setReadOnly(True)

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.ask_button)
        top_bar.addStretch()

        layout = QVBoxLayout()
        layout.addWidget(self.question_input)
        layout.addLayout(top_bar)
        layout.addWidget(self.answer_output)

        self.setLayout(layout)

    def ask(self) -> None:
        question = self.question_input.toPlainText().strip()
        if not question:
            return

        self.ask_button.setEnabled(False)
        self.answer_output.clear()
        self.answer_output.setPlaceholderText("Searching evidence...")
        run_async(
            self.api.ask_ai,
            question,
            on_done=self._on_answer,
            on_error=self._on_ask_failed,
        )

    def _on_answer(self, result: dict) -> None:
        self.ask_button.setEnabled(True)
        self.answer_output.setPlainText(self._format_answer(result))

    def _on_ask_failed(self, error: str) -> None:
        self.ask_button.setEnabled(True)
        QMessageBox.critical(self, "AI Ask Failed", error)

    @staticmethod
    def _format_answer(result: dict) -> str:
        answer = result.get("answer", "")
        citations = result.get("citations", [])

        lines = [answer, "", "Citations:"]

        for citation in citations:
            lines.append(f"- {citation}")

        return "\n".join(lines)
