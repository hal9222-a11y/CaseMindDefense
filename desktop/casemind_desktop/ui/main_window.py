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
from ui.pages.evidence_page import EvidencePage
from ui.pages.placeholder_page import PlaceholderPage
from ui.pages.search_page import SearchPage
from ui.widgets.status_bar_widget import StatusBarWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.api = ApiClient()

        self.setWindowTitle(f"{APP_NAME} - {APP_VERSION}")
        self.resize(1400, 850)

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
                "Contradictions",
                "Settings",
            ]
        )

        self.status = StatusBarWidget(self.api)

        self.pages = QStackedWidget()
        self.pages.addWidget(DashboardPage(self.status.check_backend))
        self.pages.addWidget(EvidencePage(self.api))
        self.pages.addWidget(SearchPage(self.api))
        self.pages.addWidget(AIPage(self.api))
        self.pages.addWidget(PlaceholderPage("Timeline", "Investigation timeline will live here."))
        self.pages.addWidget(PlaceholderPage("Entities", "Extracted entities will live here."))
        self.pages.addWidget(PlaceholderPage("Contradictions", "Potential evidence conflicts will live here."))
        self.pages.addWidget(PlaceholderPage("Settings", "Backend URL, theme, logs and preferences."))

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
