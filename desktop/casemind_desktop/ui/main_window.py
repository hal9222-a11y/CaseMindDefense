from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QTabWidget,
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

# Minimal line icons (stroke baked so QSvgRenderer needs no currentColor). One per
# nav entry; drawn once into a QIcon. Kept as small path data, not asset files, so
# navigation stays a single self-contained module.
_ICONS = {
    "dashboard": '<path d="M3 12h7V3H3zM14 21h7v-9h-7zM14 3v6h7V3zM3 21h7v-6H3z"/>',
    "evidence": '<path d="M4 4h11l5 5v11H4z"/><path d="M15 4v5h5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/>',
    "timeline": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "people": '<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="18" cy="9" r="2.2"/>',
    "contradictions": '<path d="M12 3v18M5 8l7-5 7 5M5 16l7 5 7-5"/>',
    "assistant": '<path d="M9 3h6v3l3 2v6l-3 2v3H9v-3l-3-2V8l3-2z"/><circle cx="12" cy="11" r="2"/>',
    "insights": '<path d="M12 3a6 6 0 0 1 3 11v3H9v-3a6 6 0 0 1 3-11z"/><path d="M9 21h6"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
}


def _icon(key: str, color: str = "#c7d2e6", size: int = 18) -> QIcon:
    """Render one of the line icons to a QIcon; empty QIcon if SVG is unavailable."""
    body = _ICONS.get(key)
    if body is None:
        return QIcon()
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'width="{size}" height="{size}" fill="none" stroke="{color}" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )
    try:
        from PySide6.QtSvg import QSvgRenderer
    except Exception:
        return QIcon()
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


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

        # --- pages ---
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
        self.claim_contradictions_page = DataPage(
            "Claim Contradictions",
            [
                ("Claim A", "claim_a"),
                ("Claim B", "claim_b"),
                ("Type", "type"),
                ("Severity", "severity"),
                ("Verified", "verified"),
                ("Source A", "source_a"),
                ("Source B", "source_b"),
                ("Explanation", "explanation"),
            ],
            self.api.claim_contradictions,
            note="Atomic-claim contradictions across statements — double-click opens evidence A",
        )
        self.graph_page = GraphPage(self.api)
        self.persons_page = PersonsPage(self.api)
        self.insights_page = InsightsPage(self.api)
        self.insights_page.open_citation.connect(self._open_citation)

        # --- merged views (concept A): the three entity screens and the two
        # contradiction screens each collapse into one tabbed destination, so the
        # nav has one clear entry instead of three near-duplicates.
        self.people_tabs = QTabWidget()
        self.people_tabs.addTab(self.persons_page, "אנשים · People")
        self.people_tabs.addTab(self.entities_page, "ישויות · Entities")
        self.people_tabs.addTab(self.graph_page, "גרף קשרים · Graph")

        self.contradictions_tabs = QTabWidget()
        self.contradictions_tabs.addTab(self.contradictions_page, "לפי קובץ · By file")
        self.contradictions_tabs.addTab(self.claim_contradictions_page, "לפי טענה · By claim")

        # --- signal wiring (unchanged inner pages) ---
        self.search_page.results.result_selected.connect(self._open_citation)
        self.ai_page.citations.result_selected.connect(self._open_citation)
        self.timeline_page.table.row_activated.connect(self._open_citation)
        self.contradictions_page.table.row_activated.connect(self._open_citation)
        self.claim_contradictions_page.table.row_activated.connect(self._open_citation)
        self.entities_page.table.row_activated.connect(self._search_entity)
        self.graph_page.entity_activated.connect(
            lambda entity: self._search_entity({"entity": entity})
        )
        self.evidence_page.case_scope_changed.connect(self._on_scope_changed)

        # status bar first — the dashboard's "check backend" button wires to it
        self.status = StatusBarWidget(self.api)

        # --- page stack; remember indices we navigate to programmatically ---
        self.pages = QStackedWidget()
        idx_dashboard = self._add_page(DashboardPage(self.status.check_backend))
        self._idx_evidence = self._add_page(self.evidence_page)
        self._idx_search = self._add_page(self.search_page)
        idx_timeline = self._add_page(self.timeline_page)
        idx_people = self._add_page(self.people_tabs)
        idx_contra = self._add_page(self.contradictions_tabs)
        idx_ai = self._add_page(self.ai_page)
        idx_insights = self._add_page(self.insights_page)
        idx_settings = self._add_page(SettingsPage(self.api))

        # --- grouped, bilingual sidebar ---
        # (Hebrew · English, icon, page index). Group headers are non-selectable.
        groups = [
            ("התיק · CASE", [
                ("סקירה · Dashboard", "dashboard", idx_dashboard),
                ("ראיות · Evidence", "evidence", self._idx_evidence),
                ("חיפוש · Search", "search", self._idx_search),
            ]),
            ("ניתוח · ANALYSIS", [
                ("ציר זמן · Timeline", "timeline", idx_timeline),
                ("אנשים וקשרים · People & Links", "people", idx_people),
                ("סתירות · Contradictions", "contradictions", idx_contra),
            ]),
            ("בינה · AI", [
                ("עוזר AI · Assistant", "assistant", idx_ai),
                ("תובנות · Insights", "insights", idx_insights),
            ]),
            ("מערכת · SYSTEM", [
                ("הגדרות · Settings", "settings", idx_settings),
            ]),
        ]

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(248)
        self.sidebar.setIconSize(QSize(18, 18))
        for title, items in groups:
            self._add_header(title)
            for label, icon_key, page_index in items:
                self._add_nav(label, icon_key, page_index)

        self.sidebar.currentItemChanged.connect(self._on_nav_changed)
        self._select_page(idx_dashboard)

        # --- layout ---
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.pages)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.setStatusBar(self.status)

        self.apply_dark_theme()
        self.status.check_backend()

    # ---- sidebar builders ----
    def _add_page(self, widget: QWidget) -> int:
        return self.pages.addWidget(widget)

    def _add_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)  # not selectable, not focusable
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QColor("#6b7891"))
        item.setSizeHint(QSize(0, 34))
        self.sidebar.addItem(item)

    def _add_nav(self, label: str, icon_key: str, page_index: int) -> None:
        item = QListWidgetItem(_icon(icon_key), label)
        item.setData(Qt.UserRole, page_index)
        item.setSizeHint(QSize(0, 40))
        self.sidebar.addItem(item)

    def _select_page(self, page_index: int) -> None:
        """Select the sidebar item that opens `page_index` (indices no longer
        equal rows now that headers share the list)."""
        for row in range(self.sidebar.count()):
            item = self.sidebar.item(row)
            if item.data(Qt.UserRole) == page_index:
                self.sidebar.setCurrentItem(item)
                return

    # ---- navigation ----
    def _on_nav_changed(self, current: QListWidgetItem, _previous: QListWidgetItem) -> None:
        if current is None:
            return
        page_index = current.data(Qt.UserRole)
        if page_index is not None:
            self.pages.setCurrentIndex(page_index)

    def _on_scope_changed(self, _case_id: object) -> None:
        for page in (self.timeline_page, self.entities_page, self.persons_page,
                     self.contradictions_page, self.claim_contradictions_page,
                     self.graph_page, self.insights_page):
            page.reset()
        # search/AI are user-triggered and will use the new scope on next run

    def _open_citation(self, result: dict) -> None:
        evidence_id = result.get("evidence_id")
        if evidence_id is None:
            return
        self._select_page(self._idx_evidence)
        self.evidence_page.focus_evidence(evidence_id, result.get("text"))

    def _search_entity(self, row: dict) -> None:
        entity = (row.get("entity") or "").strip()
        if not entity:
            return
        self._select_page(self._idx_search)
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
                padding: 8px 8px 16px 8px;
                outline: 0;
                font-size: 14.5px;
            }

            QListWidget::item {
                padding: 6px 12px;
                border-radius: 8px;
                color: #DBE3F0;
            }

            QListWidget::item:hover {
                background: #243044;
            }

            QListWidget::item:selected {
                background: #2563EB;
                color: white;
            }

            QTabWidget::pane {
                border: none;
            }

            QTabBar::tab {
                background: #1F2937;
                color: #9AA7BD;
                padding: 8px 16px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-inline-end: 3px;
                font-weight: bold;
            }

            QTabBar::tab:selected {
                background: #2563EB;
                color: white;
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
