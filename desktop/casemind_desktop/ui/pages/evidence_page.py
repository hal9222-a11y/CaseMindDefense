from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from api.client import ApiClient
from controllers.evidence_controller import EvidenceController
from ui.widgets.evidence_table_widget import EvidenceTableWidget
from ui.widgets.inspector_widget import InspectorWidget
from ui.widgets.preview_widget import PreviewWidget
from ui.widgets.toolbar_widget import ToolbarWidget

FILE_DIALOG_FILTER = (
    "Evidence Files (*.txt *.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)"
    ";;All Files (*)"
)


class EvidencePage(QWidget):
    """Thin orchestrator: wires toolbar, table, preview, and inspector widgets
    to the EvidenceController."""

    def __init__(self, api: ApiClient | None = None) -> None:
        super().__init__()

        self.api = api or ApiClient()
        self.controller = EvidenceController(self.api)

        self.toolbar = ToolbarWidget()
        self.table = EvidenceTableWidget()
        self.preview = PreviewWidget(self.api)
        self.inspector = InspectorWidget()

        self.toolbar.refresh_clicked.connect(self._refresh)
        self.toolbar.import_clicked.connect(self._pick_and_import)

        self.table.evidence_selected.connect(self.preview.show_evidence)
        self.table.evidence_selected.connect(self.inspector.show_evidence)

        self.controller.evidence_loaded.connect(self._on_loaded)
        self.controller.load_failed.connect(self._on_load_failed)
        self.controller.import_done.connect(self._on_import_done)
        self.controller.import_failed.connect(self._on_import_failed)

        table_panel = QWidget()
        table_layout = QVBoxLayout()
        table_layout.addWidget(QLabel("Evidence Browser"))
        table_layout.addWidget(self.table)
        table_panel.setLayout(table_layout)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(table_panel)
        splitter.addWidget(self.preview)
        splitter.addWidget(self.inspector)
        splitter.setSizes([650, 500, 350])

        layout = QVBoxLayout()
        layout.addWidget(self.toolbar)
        layout.addWidget(splitter)
        self.setLayout(layout)

        self._refresh()

    def _refresh(self) -> None:
        self.toolbar.set_busy(True)
        self.controller.load_evidence()

    def _pick_and_import(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Evidence", "", FILE_DIALOG_FILTER
        )
        if not file_path:
            return
        self.toolbar.set_busy(True)
        self.controller.import_file(file_path)

    def _on_loaded(self, items: list[dict[str, Any]]) -> None:
        self.toolbar.set_busy(False)
        self.table.set_items(items)

    def _on_load_failed(self, error: str) -> None:
        self.toolbar.set_busy(False)
        QMessageBox.critical(self, "Evidence Load Failed", error)

    def _on_import_done(self, _result: dict[str, Any]) -> None:
        self._refresh()
        QMessageBox.information(self, "Import Complete", "Evidence imported successfully.")

    def _on_import_failed(self, error: str) -> None:
        self.toolbar.set_busy(False)
        QMessageBox.critical(self, "Import Failed", error)
