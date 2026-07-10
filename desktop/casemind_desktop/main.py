import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from PySide6.QtWidgets import QApplication, QMessageBox

from backend_launcher import ensure_backend
from ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("CaseMind Defense")

    if not ensure_backend():
        QMessageBox.warning(
            None,
            "Backend Unavailable",
            "לא הצלחתי להפעיל את שרת ה-backend.\n"
            "בדוק ש-backend/.venv קיים (הרץ את scripts/setup.ps1) "
            "או הפעל ידנית:\n"
            "cd backend; .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app",
        )

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
