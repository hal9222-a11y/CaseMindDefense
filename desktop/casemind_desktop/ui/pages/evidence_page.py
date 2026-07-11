from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from workers.api_worker import run_async

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
        self.toolbar.import_folder_clicked.connect(self._pick_and_import_folder)
        self.toolbar.delete_clicked.connect(self._delete_selected)
        self.toolbar.new_case_clicked.connect(self._create_case)
        self.toolbar.report_clicked.connect(self._generate_report)
        self.toolbar.case_changed.connect(lambda _case_id: self._refresh())

        self._pending_highlight: str | None = None
        self._pending_focus_id: int | None = None

        self.table.evidence_selected.connect(self._on_evidence_selected)

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
        # stretch factors: toolbar stays one row tall, the splitter takes
        # all remaining height (otherwise Qt centers the toolbar in half
        # the page)
        layout.addWidget(self.toolbar, 0)
        layout.addWidget(splitter, 1)
        self.setLayout(layout)

        self._load_cases()
        self._refresh()

    def _load_cases(self) -> None:
        run_async(self.api.list_cases, on_done=self.toolbar.set_cases)

    def _create_case(self) -> None:
        name, ok = QInputDialog.getText(self, "New Case", "Case name:")
        if not ok or not name.strip():
            return
        run_async(
            self.api.create_case,
            name.strip(),
            on_done=lambda _case: self._load_cases(),
            on_error=lambda err: QMessageBox.critical(self, "Create Case Failed", err),
        )

    def _pick_and_import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Import Folder — כל הקבצים הנתמכים ייקלטו, כולל תתי-תיקיות")
        if not folder:
            return
        self.toolbar.set_busy(True)
        run_async(
            self.api.import_evidence_folder,
            folder,
            self.toolbar.current_case_id(),
            on_done=self._on_folder_imported,
            on_error=self._on_import_failed,
        )

    def _on_folder_imported(self, result: dict[str, Any]) -> None:
        self.toolbar.set_busy(True)  # stays busy through the refresh
        self._refresh()
        errors = result.get("errors") or []
        message = (
            f"נסרקו: {result.get('scanned', 0)} קבצים\n"
            f"נקלטו: {result.get('registered', 0)}\n"
            f"כפולים (דולגו): {result.get('duplicates', 0)}\n"
            f"שגיאות: {len(errors)}\n\n"
            "העיבוד (OCR / תמלול / אינדוקס) רץ ברקע — Refresh יראה התקדמות."
        )
        if errors:
            message += "\n\nשגיאות ראשונות:\n" + "\n".join(
                f"- {e.get('path', '')}: {e.get('error', '')}" for e in errors[:5]
            )
        QMessageBox.information(self, "Folder Import", message)

    def _generate_report(self) -> None:
        run_async(
            self.api.generate_report,
            self.toolbar.current_case_id(),
            on_done=self._on_report_ready,
            on_error=lambda err: QMessageBox.critical(self, "Report Failed", err),
        )

    def _on_report_ready(self, result: dict[str, Any]) -> None:
        import os

        QMessageBox.information(
            self,
            "Report Ready",
            f"הדוח נוצר: {result.get('case_name')}\n"
            f"{result.get('evidence_count')} ראיות · "
            f"{result.get('timeline_events')} אירועי ציר זמן · "
            f"{result.get('entities')} ישויות\n\nנפתח בדפדפן (Ctrl+P להדפסה כ-PDF).",
        )
        path = result.get("path")
        if path:
            os.startfile(path)  # noqa: S606 (local file, user-initiated)

    def _refresh(self) -> None:
        self.toolbar.set_busy(True)
        self.controller.load_evidence(self.toolbar.current_case_id())

    def _pick_and_import(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Evidence", "", FILE_DIALOG_FILTER
        )
        if not file_path:
            return
        self.toolbar.set_busy(True)
        self.controller.import_file(file_path, self.toolbar.current_case_id())

    def _on_evidence_selected(self, item: dict[str, Any]) -> None:
        self.preview.show_evidence(item, highlight=self._pending_highlight)
        self.inspector.show_evidence(item)
        self._pending_highlight = None
        self.toolbar.set_delete_enabled(True)

    def _delete_selected(self) -> None:
        item = self.table.current_item()
        if item is None:
            return
        filename = item.get("filename", "")
        confirm = QMessageBox.question(
            self,
            "מחיקת ראיה",
            f"למחוק לצמיתות את הראיה?\n\n{filename}\n\n"
            "הקובץ המאוחסן והאינדוקס יימחקו. הפעולה תירשם ביומן הפעולות "
            "ואינה הפיכה.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.toolbar.set_busy(True)
        run_async(
            self.api.delete_evidence,
            item.get("id"),
            on_done=lambda _res: self._on_deleted(filename),
            on_error=self._on_delete_failed,
        )

    def _on_deleted(self, filename: str) -> None:
        self.preview.clear()
        self.inspector.clear()
        self.toolbar.set_delete_enabled(False)
        self._refresh()
        QMessageBox.information(self, "נמחק", f"הראיה נמחקה:\n{filename}")

    def _on_delete_failed(self, error: str) -> None:
        self.toolbar.set_busy(False)
        QMessageBox.critical(self, "מחיקה נכשלה", error)

    def focus_evidence(self, evidence_id: int, snippet: str | None = None) -> None:
        """Citation navigation: select the evidence row and highlight the
        cited chunk in the preview. Reloads the list first if the row is
        not present yet."""
        self._pending_highlight = snippet
        if not self.table.select_by_id(evidence_id):
            self._pending_focus_id = evidence_id
            self._refresh()

    def _on_loaded(self, items: list[dict[str, Any]]) -> None:
        self.toolbar.set_busy(False)
        self.toolbar.set_delete_enabled(False)  # selection is cleared on reload
        self.table.set_items(items)
        if self._pending_focus_id is not None:
            found = self.table.select_by_id(self._pending_focus_id)
            self._pending_focus_id = None
            if not found:
                self._pending_highlight = None
                QMessageBox.information(
                    self, "Not Found", "The cited evidence is not in the list."
                )

    def _on_load_failed(self, error: str) -> None:
        self.toolbar.set_busy(False)
        QMessageBox.critical(self, "Evidence Load Failed", error)

    def _on_import_done(self, _result: dict[str, Any]) -> None:
        self._refresh()
        QMessageBox.information(self, "Import Complete", "Evidence imported successfully.")

    def _on_import_failed(self, error: str) -> None:
        self.toolbar.set_busy(False)
        QMessageBox.critical(self, "Import Failed", error)
