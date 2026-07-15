"""Headless check for the status bar. A tooltip edit once dropped the
showMessage() call, leaving the bar stuck on "בודק חיבור לשרת" forever even
though it was polling successfully. Run with QT_QPA_PLATFORM=offscreen.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "casemind_desktop"))

from PySide6.QtWidgets import QApplication  # noqa: E402
from ui.widgets.status_bar_widget import StatusBarWidget  # noqa: E402

_app = QApplication.instance() or QApplication([])

STATUS = {
    "ok": True, "evidence_total": 485, "processing": 11, "busy": True,
    "current": {"filename": "x.opus", "stage": "תמלול"},
    "indexed": 409, "no_text": 65, "failed": 0,
    "translated": 11, "to_translate": 383,
    "llm_available": False, "background_enabled": True,
}


class _FakeApi:
    current_case_id = None


def test_on_status_replaces_the_checking_message():
    w = StatusBarWidget(_FakeApi())
    w.showMessage("בודק חיבור לשרת…")   # the stuck state
    w._on_status(dict(STATUS))
    msg = w.currentMessage()
    assert msg != "בודק חיבור לשרת…", "the bar never left the checking state"
    assert "תמלול" in msg and "x.opus" in msg   # it shows the real activity


def test_paused_state_is_shown():
    w = StatusBarWidget(_FakeApi())
    w._on_status({**STATUS, "background_enabled": False})
    assert "מושהה" in w.currentMessage()


if __name__ == "__main__":
    # runnable without pytest: `python tests/test_status_bar.py`
    test_on_status_replaces_the_checking_message()
    test_paused_state_is_shown()
    print("status bar self-check passed")
