"""Headless check for the grouped bilingual sidebar (concept A). Navigation used
to be row-index == page-index; once group headers share the list that no longer
holds, so this pins the mapping: every nav item opens the right page, headers are
non-selectable, and the merged tabbed views are present. Run with
QT_QPA_PLATFORM=offscreen.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "casemind_desktop"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _window():
    # don't hit the network while constructing the window
    from ui.widgets import status_bar_widget
    status_bar_widget.StatusBarWidget.check_backend = lambda self: None
    from ui.main_window import MainWindow
    return MainWindow()


def test_sidebar_groups_and_page_mapping():
    w = _window()
    # 9 destinations (12 screens, entities/persons/graph and the two
    # contradiction views merged) + 4 group headers = 13 rows
    assert w.pages.count() == 9
    headers = [w.sidebar.item(r) for r in range(w.sidebar.count())
               if not (w.sidebar.item(r).flags() & Qt.ItemIsSelectable)]
    assert len(headers) == 4

    # every selectable item carries a valid page index and opens exactly it
    for r in range(w.sidebar.count()):
        item = w.sidebar.item(r)
        page_index = item.data(Qt.UserRole)
        if page_index is None:
            continue  # header
        w.sidebar.setCurrentItem(item)
        assert w.pages.currentIndex() == page_index


def test_programmatic_nav_targets_and_merged_tabs():
    w = _window()
    w._select_page(w._idx_evidence)
    assert w.pages.currentIndex() == w._idx_evidence
    w._select_page(w._idx_search)
    assert w.pages.currentIndex() == w._idx_search
    # merged views keep every original screen reachable as a tab
    assert w.people_tabs.count() == 3          # persons / entities / graph
    assert w.contradictions_tabs.count() == 2  # by-file / by-claim


if __name__ == "__main__":
    # runnable without pytest: `python tests/test_main_window.py`
    test_sidebar_groups_and_page_mapping()
    test_programmatic_nav_targets_and_merged_tabs()
    print("main window self-check passed")
