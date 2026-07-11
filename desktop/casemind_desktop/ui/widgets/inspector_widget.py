from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

FIELDS = [
    ("ID", "id"),
    ("Filename", "filename"),
    ("MIME Type", "mime_type"),
    ("Status", "status"),
    ("Size (bytes)", "size_bytes"),
    ("Imported At", "imported_at"),
    ("SHA256", "sha256"),
    ("Original Path", "original_path"),
    ("Stored Path", "stored_path"),
]


class InspectorWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self._view = QTextEdit()
        self._view.setReadOnly(True)
        self._view.setPlaceholderText("Evidence metadata will appear here.")

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Inspector"))
        layout.addWidget(self._view)
        self.setLayout(layout)

    def show_evidence(self, item: dict[str, Any]) -> None:
        lines = []
        for label, key in FIELDS:
            lines.append(f"{label}:")
            lines.append(str(item.get(key, "")))
            lines.append("")
        self._view.setPlainText("\n".join(lines).strip())

    def clear(self) -> None:
        self._view.clear()
