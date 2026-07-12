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
    import_folder_clicked = Signal()
    delete_clicked = Signal()
    new_case_clicked = Signal()
    delete_case_clicked = Signal()
    report_clicked = Signal()
    case_changed = Signal(object)  # int case id, or None for "All Cases"

    def __init__(self) -> None:
        super().__init__()

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.refresh_button = QPushButton("Refresh")
        self.import_button = QPushButton("Import File")
        self.import_folder_button = QPushButton("Import Folder")
        self.delete_button = QPushButton("Delete")
        # destructive: red, and disabled until a row is selected
        self.delete_button.setStyleSheet(
            "QPushButton { background: #b91c1c; } QPushButton:hover { background: #dc2626; }"
            "QPushButton:disabled { background: #4b5563; }"
        )
        self.delete_button.setEnabled(False)
        self.new_case_button = QPushButton("New Case")
        self.delete_case_button = QPushButton("Delete Case")
        self.delete_case_button.setStyleSheet(
            "QPushButton { background: #b91c1c; } QPushButton:hover { background: #dc2626; }"
            "QPushButton:disabled { background: #4b5563; }"
        )
        self.delete_case_button.setEnabled(False)  # only when a real case is selected
        self.report_button = QPushButton("Report")
        self.case_selector = QComboBox()
        self.case_selector.setMinimumWidth(180)

        self.refresh_button.clicked.connect(self.refresh_clicked)
        self.import_button.clicked.connect(self.import_clicked)
        self.import_folder_button.clicked.connect(self.import_folder_clicked)
        self.delete_button.clicked.connect(self.delete_clicked)
        self.new_case_button.clicked.connect(self.new_case_clicked)
        self.delete_case_button.clicked.connect(self.delete_case_clicked)
        self.report_button.clicked.connect(self.report_clicked)
        self.case_selector.currentIndexChanged.connect(self._on_case_changed)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Case:"))
        layout.addWidget(self.case_selector)
        layout.addWidget(self.new_case_button)
        layout.addWidget(self.delete_case_button)
        layout.addSpacing(16)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.import_button)
        layout.addWidget(self.import_folder_button)
        layout.addWidget(self.delete_button)
        layout.addWidget(self.report_button)
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
        self.delete_case_button.setEnabled(self.current_case_id() is not None)

    def current_case_id(self) -> int | None:
        return self.case_selector.currentData()

    def _on_case_changed(self, _index: int) -> None:
        case_id = self.current_case_id()
        self.delete_case_button.setEnabled(case_id is not None)
        self.case_changed.emit(case_id)

    def set_delete_enabled(self, enabled: bool) -> None:
        self.delete_button.setEnabled(enabled)

    def set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        self.import_button.setEnabled(not busy)
        self.import_folder_button.setEnabled(not busy)
        if busy:
            self.delete_button.setEnabled(False)
