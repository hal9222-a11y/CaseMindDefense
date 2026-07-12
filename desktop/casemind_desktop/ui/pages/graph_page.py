from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsEllipseItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from api.client import ApiClient
from workers.api_worker import run_async

TYPE_COLORS = {
    "person": "#3B82F6",
    "organization": "#8B5CF6",
    "location": "#22C55E",
    "phone": "#F59E0B",
    "israeli_id": "#EF4444",
    "vehicle_plate": "#EC4899",
    "time": "#14B8A6",
}
DEFAULT_COLOR = "#9CA3AF"
RADIUS = 300  # circle layout radius


class GraphPage(QWidget):
    """Entity co-occurrence graph. Circle layout — node size by count,
    color by type, edge width by shared-evidence weight. Double-click a
    node to search its occurrences."""

    entity_activated = Signal(str)

    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api
        self._loaded_once = False

        self.scene = QGraphicsScene()
        self.view = _GraphView(self.scene, self._on_node_double_clicked)

        self.mode_selector = QComboBox()
        self.mode_selector.addItem("Entities", "entities")
        self.mode_selector.addItem("People (relations)", "people")
        self.mode_selector.currentIndexChanged.connect(self._on_mode_changed)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        title = QLabel("Graph")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.legend = QLabel("size = mentions · edge = shared evidence · double-click = search")
        self.legend.setStyleSheet("color: #9CA3AF;")

        top_bar = QHBoxLayout()
        top_bar.addWidget(title)
        top_bar.addWidget(self.mode_selector)
        top_bar.addWidget(self.legend)
        top_bar.addStretch()
        top_bar.addWidget(self.refresh_button)

        layout = QVBoxLayout()
        layout.addLayout(top_bar)
        layout.addWidget(self.view)
        self.setLayout(layout)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        if not self._loaded_once:
            self._loaded_once = True
            self.refresh()

    def _mode(self) -> str:
        return self.mode_selector.currentData()

    def _on_mode_changed(self, _index: int) -> None:
        people = self._mode() == "people"
        self.legend.setText(
            "אנשים · קו = קשר (אח / אבא של…) · double-click = חיפוש"
            if people
            else "size = mentions · edge = shared evidence · double-click = search"
        )
        self.refresh()

    def refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        if self._mode() == "people":
            if self.api.current_case_id is None:
                self.refresh_button.setEnabled(True)
                self.scene.clear()
                self.scene.addText("בחר תיק ספציפי בדף Evidence כדי לראות את רשת האנשים.")
                return
            run_async(self.api.person_graph, self.api.current_case_id,
                      on_done=self._on_people_loaded, on_error=self._on_failed)
        else:
            run_async(self.api.entity_graph, on_done=self._on_loaded, on_error=self._on_failed)

    def reset(self) -> None:
        """Force a reload next time shown (used when the case scope changes)."""
        self._loaded_once = False
        self.scene.clear()

    def _on_loaded(self, graph: dict) -> None:
        self.refresh_button.setEnabled(True)
        self._draw(graph)

    def _on_people_loaded(self, graph: dict) -> None:
        self.refresh_button.setEnabled(True)
        self._draw_people(graph)

    def _on_failed(self, error: str) -> None:
        self.refresh_button.setEnabled(True)
        QMessageBox.critical(self, "Graph Load Failed", error)

    def _draw(self, graph: dict) -> None:
        self.scene.clear()
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        if not nodes:
            self.scene.addText("No entities yet — import and index evidence first.")
            return

        positions: dict[str, QPointF] = {}
        for i, node in enumerate(nodes):
            angle = 2 * math.pi * i / len(nodes)
            positions[node["entity"]] = QPointF(
                RADIUS * math.cos(angle), RADIUS * math.sin(angle)
            )

        for edge in edges:
            a, b = positions.get(edge["a"]), positions.get(edge["b"])
            if a is None or b is None:
                continue
            width = min(1 + edge.get("weight", 1), 6)
            pen = QPen(QColor("#4B5563"), width)
            self.scene.addLine(a.x(), a.y(), b.x(), b.y(), pen)

        for node in nodes:
            pos = positions[node["entity"]]
            size = 14 + min(int(math.log(node.get("count", 1) + 1) * 10), 30)
            color = QColor(TYPE_COLORS.get(node.get("type"), DEFAULT_COLOR))
            item = QGraphicsEllipseItem(
                pos.x() - size / 2, pos.y() - size / 2, size, size
            )
            item.setBrush(QBrush(color))
            item.setPen(QPen(Qt.NoPen))
            item.setToolTip(f"{node['entity']} ({node.get('type')}, {node.get('count')})")
            item.setData(0, node["entity"])
            self.scene.addItem(item)

            label = self.scene.addText(node["entity"])
            label.setDefaultTextColor(QColor("#F9FAFB"))
            label.setPos(pos.x() + size / 2 + 2, pos.y() - 10)

        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)

    def _draw_people(self, graph: dict) -> None:
        self.scene.clear()
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        if not nodes:
            self.scene.addText("אין אנשים בתיק. הוסף אנשים בדף Persons.")
            return

        pos: dict[int, QPointF] = {}
        for i, node in enumerate(nodes):
            angle = 2 * math.pi * i / len(nodes)
            pos[node["id"]] = QPointF(RADIUS * math.cos(angle), RADIUS * math.sin(angle))

        for edge in edges:
            a, b = pos.get(edge["a"]), pos.get(edge["b"])
            if a is None or b is None:
                continue
            self.scene.addLine(a.x(), a.y(), b.x(), b.y(), QPen(QColor("#4B5563"), 2))
            if edge.get("label"):
                lbl = self.scene.addText(edge["label"])
                lbl.setDefaultTextColor(QColor("#93C5FD"))
                lbl.setPos((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)

        for node in nodes:
            p = pos[node["id"]]
            size = 26
            # blue = appears in evidence, grey = added manually
            color = QColor("#3B82F6" if node.get("in_evidence", True) else "#9CA3AF")
            item = QGraphicsEllipseItem(p.x() - size / 2, p.y() - size / 2, size, size)
            item.setBrush(QBrush(color))
            item.setPen(QPen(Qt.NoPen))
            tip = node["name"] + (f" — {node['description']}" if node.get("description") else "")
            item.setToolTip(tip)
            item.setData(0, node["name"])
            self.scene.addItem(item)
            label = self.scene.addText(node["name"])
            label.setDefaultTextColor(QColor("#F9FAFB"))
            label.setPos(p.x() + size / 2 + 2, p.y() - 10)

        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)

    def _on_node_double_clicked(self, entity: str) -> None:
        self.entity_activated.emit(entity)


class _GraphView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, on_node_double_clicked) -> None:
        super().__init__(scene)
        self._on_node_double_clicked = on_node_double_clicked
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt override)
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, QGraphicsEllipseItem) and item.data(0):
            self._on_node_double_clicked(item.data(0))
        super().mouseDoubleClickEvent(event)
