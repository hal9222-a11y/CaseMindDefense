from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from config.settings import APP_VERSION


class DashboardPage(QWidget):
    def __init__(self, check_backend_callback) -> None:
        super().__init__()

        title = QLabel("CaseMind Defense")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 30px; font-weight: bold;")

        subtitle = QLabel(f"Desktop {APP_VERSION}")
        subtitle.setAlignment(Qt.AlignCenter)

        button = QPushButton("Check Backend Connection")
        button.clicked.connect(check_backend_callback)

        layout = QVBoxLayout()
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(button)
        layout.addStretch()

        self.setLayout(layout)
