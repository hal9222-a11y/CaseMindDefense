from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class ToolbarWidget(QWidget):
    refresh_clicked = Signal()
    import_clicked = Signal()
    new_case_clicked = Signal()
    case_changed = Signal(object)  # int case id, or None for "All Cases"

    def __init__(self) -> None:
        super().__init__()

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.refresh_button = QPushButton("Refresh")
        self.import_button = QPushButton("Import Evidence")
        self.new_case_button = QPushButton("New Case")
        self.case_selector = QComboBox()
        self.case_selector.setMinimumWidth(180)

        self.refresh_button.clicked.connect(self.refresh_clicked)
        self.import_button.clicked.connect(self.import_clicked)
        self.new_case_button.clicked.connect(self.new_case_clicked)
        self.case_selector.currentIndexChanged.connect(self._on_case_changed)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Case:"))
        layout.addWidget(self.case_selector)
        layout.addWidget(self.new_case_button)
        layout.addSpacing(16)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.import_button)
        layout.addStretch()
        self.setLayout(layout)

    def set_cases(self, cases: list[dict[str, Any]]) -> None:
        selected = self.current_case_id()
        self.case_selector.blockSignals(True)
        self.case_selector.clear()
        self.case_selector.addItem("All Cases", None)
        for case in cases:
            self.case_selector.addItem(case.get("name", ""), case.get("id"))
            if case.get("id") == selected:
                self.case_selector.setCurrentIndex(self.case_selector.count() - 1)
        self.case_selector.blockSignals(False)

    def current_case_id(self) -> int | None:
        return self.case_selector.currentData()

    def _on_case_changed(self, _index: int) -> None:
        self.case_changed.emit(self.current_case_id())

    def set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        self.import_button.setEnabled(not busy)
