from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from api.client import ApiClient
from workers.api_worker import run_async


class EvidencePage(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.api = ApiClient()
        self.evidence_items: list[dict[str, Any]] = []

        self.refresh_button = QPushButton("Refresh")
        self.import_button = QPushButton("Import Evidence")

        self.refresh_button.clicked.connect(self.load_evidence)
        self.import_button.clicked.connect(self.import_evidence)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.import_button)
        toolbar.addStretch()

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Filename", "Type", "Size", "Status", "Imported", "SHA256"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Select evidence to preview.")

        self.inspector = QTextEdit()
        self.inspector.setReadOnly(True)
        self.inspector.setPlaceholderText("Evidence metadata will appear here.")

        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Evidence Browser"))
        left_layout.addWidget(self.table)
        left_panel.setLayout(left_layout)

        center_panel = QWidget()
        center_layout = QVBoxLayout()
        center_layout.addWidget(QLabel("Preview"))
        center_layout.addWidget(self.preview)
        center_panel.setLayout(center_layout)

        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Inspector"))
        right_layout.addWidget(self.inspector)
        right_panel.setLayout(right_layout)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(center_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([650, 500, 350])

        layout = QVBoxLayout()
        layout.addLayout(toolbar)
        layout.addWidget(splitter)

        self.setLayout(layout)

        self.load_evidence()

    def load_evidence(self) -> None:
        self.refresh_button.setEnabled(False)
        run_async(
            self.api.list_evidence,
            on_done=self._on_evidence_loaded,
            on_error=self._on_load_failed,
        )

    def _on_evidence_loaded(self, items: list[dict[str, Any]]) -> None:
        self.refresh_button.setEnabled(True)
        self.evidence_items = items
        self.table.setRowCount(len(self.evidence_items))

        for row, item in enumerate(self.evidence_items):
            values = [
                str(item.get("id", "")),
                item.get("filename", ""),
                item.get("mime_type", ""),
                str(item.get("size_bytes", "")),
                item.get("status", ""),
                item.get("imported_at", ""),
                self._short_hash(item.get("sha256", "")),
            ]

            for col, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                table_item.setToolTip(value)
                self.table.setItem(row, col, table_item)

        self.table.resizeColumnsToContents()

    def _on_load_failed(self, error: str) -> None:
        self.refresh_button.setEnabled(True)
        QMessageBox.critical(self, "Evidence Load Failed", error)

    def import_evidence(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Evidence",
            "",
            "Evidence Files (*.txt *.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All Files (*)",
        )

        if not file_path:
            return

        self.import_button.setEnabled(False)
        run_async(
            self.api.import_evidence_file,
            file_path,
            on_done=self._on_import_done,
            on_error=self._on_import_failed,
        )

    def _on_import_done(self, _result: dict[str, Any]) -> None:
        self.import_button.setEnabled(True)
        self.load_evidence()
        QMessageBox.information(
            self,
            "Import Complete",
            "Evidence imported successfully.",
        )

    def _on_import_failed(self, error: str) -> None:
        self.import_button.setEnabled(True)
        QMessageBox.critical(self, "Import Failed", error)

    def on_selection_changed(self) -> None:
        row = self.table.currentRow()

        if row < 0 or row >= len(self.evidence_items):
            return

        item = self.evidence_items[row]

        self.update_inspector(item)
        self.update_preview(item)

    def update_inspector(self, item: dict[str, Any]) -> None:
        text = f"""
Evidence Inspector

ID:
{item.get("id", "")}

Filename:
{item.get("filename", "")}

MIME Type:
{item.get("mime_type", "")}

Status:
{item.get("status", "")}

Size:
{item.get("size_bytes", "")} bytes

Imported At:
{item.get("imported_at", "")}

SHA256:
{item.get("sha256", "")}

Original Path:
{item.get("original_path", "")}

Stored Path:
{item.get("stored_path", "")}
""".strip()

        self.inspector.setPlainText(text)

    def update_preview(self, item: dict[str, Any]) -> None:
        filename = item.get("filename", "")
        mime_type = item.get("mime_type", "")
        status = item.get("status", "")

        preview_text = f"""
Preview

Selected Evidence:
{filename}

Type:
{mime_type}

Status:
{status}

Full PDF/Image/Text preview will be added in the next sprint.

Next:
- Text preview for TXT files
- Image preview for PNG/JPG
- PDF preview
- Citation highlighting
""".strip()

        self.preview.setPlainText(preview_text)

    def _short_hash(self, value: str) -> str:
        if not value:
            return ""
        return f"{value[:16]}..."