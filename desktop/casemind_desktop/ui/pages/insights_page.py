from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from api.client import ApiClient
from ui.widgets.data_table_widget import DataTableWidget
from workers.api_worker import run_async

_NO_LLM = {
    "no_llm": "אין מודל שפה זמין כרגע (Ollama). התובנות המבוססות-AI דורשות אותו.",
    "no_text": "אין עדיין טקסט מאונדקס בתיק.",
    "llm_failed": "המודל לא החזיר תוצאה. נסה שוב.",
}


class InsightsPage(QWidget):
    """Case-level AI understanding in one place: overview, suggested questions,
    sensitive-content flags, extracted events. Flags are offline; the rest use
    the local LLM (slow while transcription holds the GPU — it falls back to
    CPU). Double-click a flag/event row to open the cited evidence."""

    open_citation = Signal(dict)

    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api

        title = QLabel("AI Insights — תובנות")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")

        self.role_button = QPushButton("🎭 התפקיד שלי")
        self.role_button.setToolTip(
            "הגדר את תפקידך בתיק (למשל: סנגור של אמיר גורי) — כל ניתוחי ה-AI "
            "והתשובות בתיק ימוסגרו מנקודת המבט הזו"
        )
        self.weaknesses_button = QPushButton("🛡️ חולשות בתיק")
        self.weaknesses_button.setToolTip(
            "ניתוח הגנה: סתירות, פערים ראייתיים, בעיות מהימנות וקווי הגנה"
        )
        self.summary_button = QPushButton("📋 סקירת תיק")
        self.questions_button = QPushButton("❓ שאלות מוצעות")
        self.flags_button = QPushButton("🚩 סימון תוכן רגיש")
        self.events_button = QPushButton("📅 חילוץ אירועים")
        self.digest_button = QPushButton("🎧 תקציר הקלטות")
        self.dupes_button = QPushButton("♊ כפילויות")
        self.dupes_button.setToolTip("אותו תוכן שיובא בכמה פורמטים (PDF+TXT) — מכפיל ספירות")
        self.role_button.clicked.connect(self._set_role)
        self.weaknesses_button.clicked.connect(self._weaknesses)
        self.summary_button.clicked.connect(self._case_summary)
        self.questions_button.clicked.connect(self._questions)
        self.flags_button.clicked.connect(self._flags)
        self.events_button.clicked.connect(self._events)
        self.digest_button.clicked.connect(self._digest)
        self.dupes_button.clicked.connect(self._duplicates)

        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch()
        for b in (self.role_button, self.weaknesses_button, self.summary_button,
                  self.questions_button, self.flags_button,
                  self.events_button, self.digest_button, self.dupes_button):
            top.addWidget(b)

        # text pane for prose insights (summary / questions / digest)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText(
            "בחר תובנה למעלה. הכל מעוגן בחומר התיק ומהווה כלי-עזר להבנה — לא ראיה."
        )

        # table for row-based insights (flags / events), double-click opens source
        self.table = DataTableWidget([
            ("סוג", "kind"), ("תאריך/קטגוריה", "when"), ("מעורבים", "who"),
            ("תיאור", "what"), ("קובץ", "filename"),
        ])
        self.table.row_activated.connect(self._on_row)
        self.table.hide()

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.table, 1)
        self.setLayout(layout)

    def reset(self) -> None:
        self.text.clear()
        self.table.set_rows([])
        self.table.hide()
        self.text.show()

    def _guard(self) -> bool:
        if self.api.current_case_id is None:
            QMessageBox.information(self, "בחר תיק", "בחר תיק ספציפי בדף Evidence תחילה.")
            return False
        return True

    def _busy(self, button: QPushButton, label: str) -> None:
        button.setEnabled(False)
        button.setText(label)

    # --- role + defense analysis ---
    def _set_role(self) -> None:
        if not self._guard():
            return
        current = ""
        try:
            current = self.api.get_case(self.api.current_case_id).get("role_context", "")
        except Exception:  # noqa: BLE001 — empty prefill is fine, the save will surface errors
            pass
        role, ok = QInputDialog.getText(
            self, "התפקיד שלי בתיק",
            "לדוגמה: סנגור של אמיר גורי. ה-AI ימסגר ניתוחים ותשובות מנקודת מבט זו.\n"
            "השאר ריק כדי לנקות.",
            text=current,
        )
        if not ok:
            return
        try:
            self.api.set_case_role(self.api.current_case_id, role.strip())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "שמירת תפקיד", str(exc))
            return
        QMessageBox.information(
            self, "נשמר",
            f"התפקיד נשמר: {role.strip()}" if role.strip() else "התפקיד נוקה.",
        )

    def _weaknesses(self) -> None:
        if not self._guard():
            return
        self._busy(self.weaknesses_button, "🛡️ מנתח…")
        run_async(self.api.insight_weaknesses, self.api.current_case_id,
                  on_done=self._on_weaknesses, on_error=self._prose_error)

    def _on_weaknesses(self, result: dict[str, Any]) -> None:
        self.weaknesses_button.setEnabled(True)
        self.weaknesses_button.setText("🛡️ חולשות בתיק")
        self._show_prose(result.get("weaknesses"), result.get("reason"), result.get("model"))

    # --- prose insights ---
    def _case_summary(self) -> None:
        if not self._guard():
            return
        self._busy(self.summary_button, "📋 מסכם…")
        run_async(self.api.case_summary, self.api.current_case_id,
                  on_done=self._on_summary, on_error=self._prose_error)

    def _on_summary(self, result: dict[str, Any]) -> None:
        self.summary_button.setEnabled(True)
        self.summary_button.setText("📋 סקירת תיק")
        self._show_prose(result.get("overview"), result.get("reason"), result.get("model"))

    def _questions(self) -> None:
        if not self._guard():
            return
        self._busy(self.questions_button, "❓ חושב…")
        run_async(self.api.insight_questions, self.api.current_case_id,
                  on_done=self._on_questions, on_error=self._prose_error)

    def _on_questions(self, result: dict[str, Any]) -> None:
        self.questions_button.setEnabled(True)
        self.questions_button.setText("❓ שאלות מוצעות")
        qs = result.get("questions") or []
        if not qs:
            self._show_prose(None, result.get("reason"), None)
            return
        self._show_text("שאלות חקירה מוצעות:\n\n" + "\n".join(f"• {q}" for q in qs))

    def _digest(self) -> None:
        if not self._guard():
            return
        self._busy(self.digest_button, "🎧 מסכם הקלטות…")
        run_async(self.api.recordings_digest, self.api.current_case_id,
                  on_done=self._on_digest, on_error=self._prose_error)

    def _on_digest(self, result: dict[str, Any]) -> None:
        self.digest_button.setEnabled(True)
        self.digest_button.setText("🎧 תקציר הקלטות")
        digest = result.get("digest") or []
        if not digest:
            self._show_text("אין עדיין הקלטות מתומללות בתיק.")
            return
        lines = [f"תקציר {result.get('shown')} מתוך {result.get('count')} הקלטות מתומללות:\n"]
        for d in digest:
            who = f" [{', '.join(d['people'][:6])}]" if d.get("people") else ""
            summ = d.get("summary") or _NO_LLM.get(d.get("reason"), "—")
            lines.append(f"■ {d['filename']}{who}\n{summ}\n")
        self._show_text("\n".join(lines))

    # --- table insights ---
    def _flags(self) -> None:
        if not self._guard():
            return
        self._busy(self.flags_button, "🚩 סורק…")
        run_async(self.api.insight_flags, self.api.current_case_id,
                  on_done=self._on_flags, on_error=self._table_error)

    _CAT_HE = {"money": "כסף", "drugs": "סמים", "weapons": "נשק",
               "threats": "איומים", "sex_work": "שירותי מין"}

    def _on_flags(self, result: dict[str, Any]) -> None:
        self.flags_button.setEnabled(True)
        self.flags_button.setText("🚩 סימון תוכן רגיש")
        flags = result.get("flags") or []
        summary = result.get("summary", {}).get("by_category", {})
        rows = [{
            "kind": "🚩 " + self._CAT_HE.get(f["category"], f["category"]),
            "when": ", ".join(f.get("terms", [])[:4]),
            "who": "",
            "what": f.get("snippet", ""),
            "filename": f.get("filename", ""),
            "evidence_id": f.get("evidence_id"),
            "text": f.get("snippet", ""),
        } for f in flags]
        header = "  ·  ".join(f"{self._CAT_HE.get(k,k)}: {v}" for k, v in summary.items())
        self._show_table(rows, f"נמצאו {len(flags)} קטעים רגישים   ({header})" if rows
                         else "לא נמצא תוכן רגיש לפי הלקסיקון.")

    def _duplicates(self) -> None:
        if not self._guard():
            return
        self._busy(self.dupes_button, "♊ בודק…")
        run_async(self.api.insight_duplicates, self.api.current_case_id,
                  on_done=self._on_duplicates, on_error=self._table_error)

    def _on_duplicates(self, result: dict[str, Any]) -> None:
        self.dupes_button.setEnabled(True)
        self.dupes_button.setText("♊ כפילויות")
        groups = result.get("groups") or []
        rows = []
        for g in groups:
            names = " / ".join(m["filename"] or str(m["id"]) for m in g["members"])
            reason = "זהה" if g["reason"] == "exact" else f"דומה ({int(g['similarity']*100)}%)"
            rows.append({
                "kind": "♊ כפילות",
                "when": reason,
                "who": f"{len(g['members'])} פריטים",
                "what": names,
                "filename": "",
                "evidence_id": g["members"][0]["id"],
                "text": names,
            })
        self._show_table(rows, f"נמצאו {len(rows)} קבוצות כפילות — שקול למחוק את העותקים המיותרים"
                         if rows else "לא נמצאו כפילויות תוכן בתיק.")

    def _events(self) -> None:
        if not self._guard():
            return
        self._busy(self.events_button, "📅 מחלץ…")
        run_async(self.api.insight_events, self.api.current_case_id,
                  on_done=self._on_events, on_error=self._table_error)

    def _on_events(self, events: list[dict[str, Any]]) -> None:
        self.events_button.setEnabled(True)
        self.events_button.setText("📅 חילוץ אירועים")
        rows = [{
            "kind": "📅 אירוע",
            "when": e.get("date", ""),
            "who": ", ".join(e.get("actors", [])),
            "what": e.get("action", ""),
            "filename": "",
            "evidence_id": e.get("evidence_id"),
            "text": e.get("action", ""),
        } for e in events]
        self._show_table(rows, f"חולצו {len(rows)} אירועים" if rows
                         else "לא חולצו אירועים (או שאין מודל שפה זמין).")

    # --- helpers ---
    def _show_prose(self, body: str | None, reason: str | None, model: str | None) -> None:
        if not body:
            self._show_text(_NO_LLM.get(reason, "לא ניתן להפיק תובנה."))
            return
        tag = f"[AI · {model}]  כלי-עזר להבנה, לא ראיה\n\n" if model else ""
        self._show_text(tag + body)

    def _show_text(self, text: str) -> None:
        self.table.hide()
        self.text.show()
        self.text.setPlainText(text)

    def _show_table(self, rows: list[dict[str, Any]], note: str) -> None:
        self.text.hide()
        self.table.show()
        self.table.set_rows(rows)
        if not rows:
            self.text.show()
            self.text.setPlainText(note)
            self.table.hide()

    def _on_row(self, row: dict[str, Any]) -> None:
        if row.get("evidence_id"):
            self.open_citation.emit(row)

    def _prose_error(self, message: str) -> None:
        for b, t in ((self.summary_button, "📋 סקירת תיק"),
                     (self.questions_button, "❓ שאלות מוצעות"),
                     (self.weaknesses_button, "🛡️ חולשות בתיק"),
                     (self.digest_button, "🎧 תקציר הקלטות")):
            b.setEnabled(True)
            b.setText(t)
        QMessageBox.critical(self, "תובנות AI", message)

    def _table_error(self, message: str) -> None:
        for b, t in ((self.flags_button, "🚩 סימון תוכן רגיש"),
                     (self.events_button, "📅 חילוץ אירועים"),
                     (self.dupes_button, "♊ כפילויות")):
            b.setEnabled(True)
            b.setText(t)
        QMessageBox.critical(self, "תובנות AI", message)
