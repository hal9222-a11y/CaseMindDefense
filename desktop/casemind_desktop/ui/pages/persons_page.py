from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from api.client import ApiClient
from workers.api_worker import run_async

KIND_LABELS = {
    "alias": "כינוי / שם נוסף",
    "phone": "טלפון",
    "photo": "תמונה",
    "relation": "קשר",
}


class PersonsPage(QWidget):
    """Who-is-who for the selected case: people, their aliases, phones,
    relations and photo links. People not in the evidence can be added
    manually with a description of who they are."""

    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api
        self._persons: list[dict[str, Any]] = []
        self._selected: dict[str, Any] | None = None

        title = QLabel("Persons — מי נגד מי")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")

        self.new_button = QPushButton("New Person")
        self.new_ext_button = QPushButton("New (not in evidence)")
        self.suggest_button = QPushButton("🔍 Suggest phone links")
        self.delete_button = QPushButton("Delete Person")
        self.delete_button.setStyleSheet("QPushButton { background: #b91c1c; }")
        self.refresh_button = QPushButton("Refresh")
        self.new_button.clicked.connect(lambda: self._create_person(True))
        self.new_ext_button.clicked.connect(lambda: self._create_person(False))
        self.suggest_button.clicked.connect(self._suggest_phones)
        self.delete_button.clicked.connect(self._delete_person)
        self.refresh_button.clicked.connect(self.refresh)

        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.new_button)
        top.addWidget(self.new_ext_button)
        top.addWidget(self.suggest_button)
        top.addWidget(self.delete_button)
        top.addWidget(self.refresh_button)

        self.person_list = QListWidget()
        self.person_list.setMaximumWidth(280)
        self.person_list.currentRowChanged.connect(self._on_person_selected)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("בחר אדם כדי לראות ולערוך את הפרטים.")

        self.add_alias_button = QPushButton("+ כינוי")
        self.add_phone_button = QPushButton("+ טלפון")
        self.add_relation_button = QPushButton("+ קשר")
        self.add_photo_button = QPushButton("+ תמונה")
        self.remove_link_button = QPushButton("- הסר קישור")
        self.add_alias_button.clicked.connect(lambda: self._add_simple_link("alias", "כינוי / שם חיבה:"))
        self.add_phone_button.clicked.connect(lambda: self._add_simple_link("phone", "מספר טלפון:"))
        self.add_relation_button.clicked.connect(self._add_relation)
        self.add_photo_button.clicked.connect(self._add_photo)
        self.remove_link_button.clicked.connect(self._remove_link)
        for b in (self.add_alias_button, self.add_phone_button, self.add_relation_button,
                  self.add_photo_button, self.remove_link_button):
            b.setEnabled(False)

        link_bar = QHBoxLayout()
        for b in (self.add_alias_button, self.add_phone_button, self.add_relation_button,
                  self.add_photo_button, self.remove_link_button):
            link_bar.addWidget(b)
        link_bar.addStretch()

        right = QVBoxLayout()
        right.addWidget(self.detail)
        right.addLayout(link_bar)
        right_panel = QWidget()
        right_panel.setLayout(right)

        body = QHBoxLayout()
        body.addWidget(self.person_list)
        body.addWidget(right_panel, 1)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addLayout(body, 1)
        self.setLayout(layout)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    def reset(self) -> None:
        self._persons = []
        self._selected = None
        self.person_list.clear()
        self.detail.clear()

    # --- data ---
    def refresh(self) -> None:
        case_id = self.api.current_case_id
        if case_id is None:
            self.person_list.clear()
            self.detail.setPlainText(
                "בחר תיק ספציפי בדף Evidence כדי לנהל את האנשים שבו."
            )
            self._set_link_buttons(False)
            return
        run_async(self.api.list_persons, case_id, on_done=self._on_loaded, on_error=self._error)

    def _on_loaded(self, persons: list[dict[str, Any]]) -> None:
        self._persons = persons
        self.person_list.clear()
        for p in persons:
            tag = "" if p["in_evidence"] else "  ⟨לא בחומרים⟩"
            item = QListWidgetItem(f"{p['name']}{tag}")
            self.person_list.addItem(item)
        self.detail.clear()
        self._selected = None
        self._set_link_buttons(False)

    def _on_person_selected(self, row: int) -> None:
        if not (0 <= row < len(self._persons)):
            self._selected = None
            self._set_link_buttons(False)
            return
        self._selected = self._persons[row]
        self._render_detail()
        self._set_link_buttons(True)

    def _name_of(self, person_id: int | None) -> str:
        for p in self._persons:
            if p["id"] == person_id:
                return p["name"]
        return f"#{person_id}"

    def _render_detail(self) -> None:
        p = self._selected
        if not p:
            return
        lines = [f"שם: {p['name']}"]
        if not p["in_evidence"]:
            lines.append("(אדם שנוסף ידנית — לא מופיע בחומרי החקירה)")
        if p["description"]:
            lines.append(f"מיהו: {p['description']}")
        lines.append("")
        by_kind: dict[str, list[str]] = {}
        for ln in p["links"]:
            if ln["kind"] == "relation":
                text = f"{ln['value'] or 'קשור ל'} → {self._name_of(ln['related_person_id'])}"
            elif ln["kind"] == "photo":
                text = f"ראיה #{ln['evidence_id']}" + (f" ({ln['value']})" if ln["value"] else "")
            else:
                text = ln["value"]
            suffix = "  [הצעת מערכת — לאישור]" if ln["confidence"] < 1.0 else ""
            by_kind.setdefault(ln["kind"], []).append(f"[{ln['id']}] {text}{suffix}")
        for kind in ("alias", "phone", "relation", "photo"):
            if by_kind.get(kind):
                lines.append(f"{KIND_LABELS[kind]}:")
                lines.extend(f"   {t}" for t in by_kind[kind])
                lines.append("")
        self.detail.setPlainText("\n".join(lines).strip())

    def _set_link_buttons(self, enabled: bool) -> None:
        for b in (self.add_alias_button, self.add_phone_button, self.add_relation_button,
                  self.add_photo_button, self.remove_link_button, self.delete_button):
            b.setEnabled(enabled)

    # --- actions ---
    def _create_person(self, in_evidence: bool) -> None:
        if self.api.current_case_id is None:
            QMessageBox.information(self, "בחר תיק", "בחר תיק ספציפי בדף Evidence תחילה.")
            return
        name, ok = QInputDialog.getText(self, "אדם חדש", "שם:")
        if not ok or not name.strip():
            return
        desc, _ = QInputDialog.getText(
            self, "אדם חדש", "מיהו? (תפקיד / קשר, למשל 'אחיו של הנאשם'):"
        )
        run_async(
            self.api.create_person, self.api.current_case_id, name.strip(), desc.strip(), in_evidence,
            on_done=lambda _p: self.refresh(), on_error=self._error,
        )

    def _delete_person(self) -> None:
        if not self._selected:
            return
        if QMessageBox.question(
            self, "מחיקת אדם", f"למחוק את '{self._selected['name']}' וכל הקישורים שלו?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        run_async(self.api.delete_person, self._selected["id"],
                  on_done=lambda _r: self.refresh(), on_error=self._error)

    def _add_simple_link(self, kind: str, prompt: str) -> None:
        if not self._selected:
            return
        value, ok = QInputDialog.getText(self, KIND_LABELS[kind], prompt)
        if not ok or not value.strip():
            return
        run_async(self.api.add_person_link, self._selected["id"], kind, value.strip(),
                  on_done=self._on_updated, on_error=self._error)

    def _add_relation(self) -> None:
        if not self._selected:
            return
        others = [p for p in self._persons if p["id"] != self._selected["id"]]
        if not others:
            QMessageBox.information(self, "אין למי לקשר", "צור אדם נוסף כדי ליצור קשר.")
            return
        names = [p["name"] for p in others]
        target, ok = QInputDialog.getItem(self, "קשר לאדם", "בחר אדם:", names, 0, False)
        if not ok:
            return
        rel_type, ok = QInputDialog.getText(
            self, "סוג הקשר", "מהו הקשר? (למשל: אח, אבא של, חבר קרוב):"
        )
        if not ok:
            return
        related = others[names.index(target)]
        run_async(
            self.api.add_person_link, self._selected["id"], "relation", rel_type.strip(),
            None, related["id"], on_done=self._on_updated, on_error=self._error,
        )

    def _add_photo(self) -> None:
        if not self._selected:
            return
        ev_id, ok = QInputDialog.getInt(
            self, "קישור תמונה", "מזהה הראיה (ID) של התמונה מדף Evidence:", 1, 1
        )
        if not ok:
            return
        caption, _ = QInputDialog.getText(self, "קישור תמונה", "כיתוב (רשות):")
        run_async(
            self.api.add_person_link, self._selected["id"], "photo", caption.strip(), ev_id,
            on_done=self._on_updated, on_error=self._error,
        )

    def _remove_link(self) -> None:
        if not self._selected or not self._selected["links"]:
            return
        labels = [f"[{ln['id']}] {ln['kind']}: {ln['value'] or ln.get('related_person_id') or ln.get('evidence_id')}"
                  for ln in self._selected["links"]]
        choice, ok = QInputDialog.getItem(self, "הסרת קישור", "בחר קישור להסרה:", labels, 0, False)
        if not ok:
            return
        link = self._selected["links"][labels.index(choice)]
        run_async(self.api.remove_person_link, self._selected["id"], link["id"],
                  on_done=self._on_updated, on_error=self._error)

    def _suggest_phones(self) -> None:
        if self.api.current_case_id is None:
            QMessageBox.information(self, "בחר תיק", "בחר תיק ספציפי בדף Evidence תחילה.")
            return
        self.suggest_button.setEnabled(False)
        run_async(
            self.api.suggest_phone_links, self.api.current_case_id,
            on_done=self._on_suggestions, on_error=self._suggest_error,
        )

    def _on_suggestions(self, suggestions: list[dict[str, Any]]) -> None:
        self.suggest_button.setEnabled(True)
        if not suggestions:
            QMessageBox.information(
                self, "אין הצעות",
                "לא נמצאו מספרי טלפון סמוכים לשמות של אנשים בתיק.\n"
                "טיפ: צור קודם את האנשים, ואז המערכת תנחש אילו טלפונים שייכים להם.",
            )
            return
        accepted = 0
        for s in suggestions:
            pct = int(s["confidence"] * 100)
            box = QMessageBox(self)
            box.setWindowTitle("הצעת קישור טלפון")
            box.setText(
                f"נראה שהטלפון {s['phone']} שייך ל'{s['person_name']}' "
                f"(ביטחון {pct}%).\n\n"
                f"מתוך: {s.get('filename') or ''}\n"
                f"הקשר: …{s.get('snippet', '')}…\n\nלקשר?"
            )
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            box.button(QMessageBox.Yes).setText("קשר")
            box.button(QMessageBox.No).setText("דלג")
            box.button(QMessageBox.Cancel).setText("עצור")
            choice = box.exec()
            if choice == QMessageBox.Cancel:
                break
            if choice == QMessageBox.Yes:
                try:
                    self.api.add_person_link(s["person_id"], "phone", s["phone"])
                    accepted += 1
                except Exception as exc:  # noqa: BLE001
                    QMessageBox.critical(self, "שגיאה", str(exc))
        if accepted:
            self.refresh()
        QMessageBox.information(self, "סיום", f"קושרו {accepted} מספרי טלפון.")

    def _suggest_error(self, message: str) -> None:
        self.suggest_button.setEnabled(True)
        QMessageBox.critical(self, "שגיאה", message)

    def _on_updated(self, person: dict[str, Any]) -> None:
        # replace the person in the list and re-render without a full reload
        for i, p in enumerate(self._persons):
            if p["id"] == person["id"]:
                self._persons[i] = person
                self._selected = person
                break
        self._render_detail()

    def _error(self, message: str) -> None:
        QMessageBox.critical(self, "שגיאה", message)
