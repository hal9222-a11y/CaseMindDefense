from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget


class ToolbarWidget(QWidget):
    refresh_clicked = Signal()
    import_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()

        self.refresh_button = QPushButton("Refresh")
        self.import_button = QPushButton("Import Evidence")

        self.refresh_button.clicked.connect(self.refresh_clicked)
        self.import_button.clicked.connect(self.import_clicked)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.import_button)
        layout.addStretch()
        self.setLayout(layout)

    def set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        self.import_button.setEnabled(not busy)
