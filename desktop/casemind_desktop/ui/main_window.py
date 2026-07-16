from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from api.client import ApiClient
from config.settings import APP_NAME, APP_VERSION
from ui.pages.ai_page import AIPage
from ui.pages.dashboard_page import DashboardPage
from ui.pages.data_page import DataPage
from ui.pages.evidence_page import EvidencePage
from ui.pages.graph_page import GraphPage
from ui.pages.insights_page import InsightsPage
from ui.pages.persons_page import PersonsPage
from ui.pages.search_page import SearchPage
from ui.pages.settings_page import SettingsPage
from ui.widgets.status_bar_widget import StatusBarWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.api = ApiClient()

        self.setWindowTitle(f"{APP_NAME} - {APP_VERSION}")
        # Fit the window to the ACTUAL screen and center it. A fixed 1400x850
        # overflowed a 1536x816 work area (common 1080p laptop at 125% DPI) —
        # the right edge of the RTL layout landed off-screen.
        available = self.screen().availableGeometry()
        width = min(1400, available.width() - 20)
        height = min(850, available.height() - 20)
        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(230)
        self.sidebar.addItems(
            [
                "Dashboard",
                "Evidence",
                "Search",
                "AI Workspace",
                "Timeline",
                "Entities",
                "Persons",
                "Contradictions",
                "Entity Graph",
                "AI Insights",
                "Settings",
            ]
        )

        self.status = StatusBarWidget(self.api)

        self.evidence_page = EvidencePage(self.api)
        self.search_page = SearchPage(self.api)
        self.ai_page = AIPage(self.api)

        self.timeline_page = DataPage(
            "Timeline",
            [
                ("Date", "normalized_date"),
                ("As Written", "date"),
                ("Evidence ID", "evidence_id"),
                ("Source", "source_location"),
                ("Snippet", "text"),
            ],
            self.api.timeline,
            note="double-click to open the evidence",
        )
        self.entities_page = DataPage(
            "Entities",
            [("Entity", "entity"), ("עברית", "hebrew"), ("Type", "type"), ("Count", "count")],
            self.api.entities,
            note="double-click to search occurrences",
            hebrew_names_fn=self.api.hebrew_names,
        )
        self.contradictions_page = DataPage(
            "Contradictions",
            [
                ("Verdict", "verdict"),
                ("File A", "filename_a"),
                ("File B", "filename_b"),
                ("Similarity", "similarity"),
                ("Explanation", "explanation"),
            ],
            self.api.contradictions,
            note="LLM-judged similar pairs — double-click opens evidence A",
        )

        self.graph_page = GraphPage(self.api)
        self.persons_page = PersonsPage(self.api)
        self.insights_page = InsightsPage(self.api)
        self.insights_page.open_citation.connect(self._open_citation)

        self.search_page.results.result_selected.connect(self._open_citation)
        self.ai_page.citations.result_selected.connect(self._open_citation)
        self.timeline_page.table.row_activated.connect(self._open_citation)
        self.contradictions_page.table.row_activated.connect(self._open_citation)
        self.entities_page.table.row_activated.connect(self._search_entity)
        self.graph_page.entity_activated.connect(
            lambda entity: self._search_entity({"entity": entity})
        )
        # changing the case scope on the Evidence page reloads the lazy
        # analysis views so they refetch for the new case
        self.evidence_page.case_scope_changed.connect(self._on_scope_changed)

        self.pages = QStackedWidget()
        self.pages.addWidget(DashboardPage(self.status.check_backend))
        self.pages.addWidget(self.evidence_page)
        self.pages.addWidget(self.search_page)
        self.pages.addWidget(self.ai_page)
        self.pages.addWidget(self.timeline_page)
        self.pages.addWidget(self.entities_page)
        self.pages.addWidget(self.persons_page)
        self.pages.addWidget(self.contradictions_page)
        self.pages.addWidget(self.graph_page)
        self.pages.addWidget(self.insights_page)
        self.pages.addWidget(SettingsPage(self.api))

        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.pages)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.setStatusBar(self.status)

        self.apply_dark_theme()
        self.status.check_backend()

    def _on_scope_changed(self, _case_id: object) -> None:
        for page in (self.timeline_page, self.entities_page, self.persons_page,
                     self.contradictions_page, self.graph_page, self.insights_page):
            page.reset()
        # search/AI are user-triggered and will use the new scope on next run

    def _open_citation(self, result: dict) -> None:
        evidence_id = result.get("evidence_id")
        if evidence_id is None:
            return
        self.sidebar.setCurrentRow(1)  # Evidence page
        self.evidence_page.focus_evidence(evidence_id, result.get("text"))

    def _search_entity(self, row: dict) -> None:
        entity = (row.get("entity") or "").strip()
        if not entity:
            return
        self.sidebar.setCurrentRow(2)  # Search page
        self.search_page.query_input.setText(entity)
        self.search_page.mode_selector.setCurrentText("Keyword")
        self.search_page.run_search()

    def apply_dark_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #111827;
                color: #F9FAFB;
                font-size: 14px;
            }

            QListWidget {
                background: #1F2937;
                border: none;
                padding: 8px;
                font-size: 15px;
            }

            QListWidget::item {
                padding: 12px;
                border-radius: 6px;
            }

            QListWidget::item:selected {
                background: #2563EB;
            }

            QPushButton {
                background: #2563EB;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 9px 14px;
                font-weight: bold;
            }

            QPushButton:hover {
                background: #1D4ED8;
            }

            QLineEdit, QTextEdit, QTableWidget {
                background: #0B1220;
                color: #F9FAFB;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 6px;
            }

            QHeaderView::section {
                background: #1F2937;
                color: #F9FAFB;
                padding: 6px;
                border: 1px solid #374151;
            }

            QStatusBar {
                background: #030712;
                color: #D1D5DB;
            }
            """
        )
