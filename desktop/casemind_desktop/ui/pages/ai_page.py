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

        try:
            result = self.api.ask_ai(question)
            self.answer_output.setPlainText(self._format_answer(result))
        except Exception as exc:
            QMessageBox.critical(self, "AI Ask Failed", str(exc))

    @staticmethod
    def _format_answer(result: dict) -> str:
        answer = result.get("answer", "")
        citations = result.get("citations", [])

        lines = [answer, "", "Citations:"]

        for citation in citations:
            lines.append(f"- {citation}")

        return "\n".join(lines)
