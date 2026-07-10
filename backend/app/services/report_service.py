from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from app.core.settings import get_settings
from app.models.evidence import AuditEvent, Case, Evidence
from app.services.entity_service import list_entities
from app.services.timeline_service import build_timeline

REPORT_VERSION = "CaseMind Defense v0.14"


def build_report_data(session: Session, case_id: int | None = None) -> dict:
    case = session.get(Case, case_id) if case_id is not None else None

    query = select(Evidence).order_by(Evidence.id)
    if case_id is not None:
        query = query.where(Evidence.case_id == case_id)
    evidence = session.exec(query).all()
    evidence_ids = {ev.id for ev in evidence}

    timeline = [
        event for event in build_timeline(session)
        if event.get("evidence_id") in evidence_ids
    ]
    entities = list_entities(session) if case_id is None else _entities_for(session, evidence_ids)

    audit = [
        event for event in session.exec(
            select(AuditEvent).order_by(AuditEvent.id)
        ).all()
        if event.evidence_id in evidence_ids
    ]

    return {
        "case_name": case.name if case else "כל התיקים",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": REPORT_VERSION,
        "evidence": evidence,
        "timeline": timeline,
        "entities": entities[:50],
        "audit": audit,
    }


def _entities_for(session: Session, evidence_ids: set) -> list[dict]:
    from collections import Counter

    from app.models.evidence import ExtractedEntity

    rows = session.exec(select(ExtractedEntity)).all()
    counts: Counter = Counter(
        (r.text, r.label) for r in rows if r.evidence_id in evidence_ids
    )
    return [
        {"entity": text, "type": label, "count": count}
        for (text, label), count in counts.most_common()
    ]


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def render_html(data: dict) -> str:
    rows_evidence = "\n".join(
        f"<tr><td>{_esc(ev.id)}</td><td>{_esc(ev.filename)}</td>"
        f"<td class='mono'>{_esc(ev.sha256)}</td><td>{_esc(ev.size_bytes)}</td>"
        f"<td>{_esc(ev.status)}</td><td>{_esc(ev.imported_at)}</td></tr>"
        for ev in data["evidence"]
    )
    rows_timeline = "\n".join(
        f"<tr><td>{_esc(e.get('normalized_date') or e.get('date'))}</td>"
        f"<td>{_esc(e.get('evidence_id'))}</td><td>{_esc(e.get('source_location'))}</td>"
        f"<td>{_esc(e.get('text'))}</td></tr>"
        for e in data["timeline"]
    )
    rows_entities = "\n".join(
        f"<tr><td>{_esc(e['entity'])}</td><td>{_esc(e['type'])}</td><td>{_esc(e['count'])}</td></tr>"
        for e in data["entities"]
    )
    rows_audit = "\n".join(
        f"<tr><td>{_esc(a.created_at)}</td><td>{_esc(a.event_type)}</td>"
        f"<td>{_esc(a.evidence_id)}</td></tr>"
        for a in data["audit"]
    )

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="utf-8">
<title>דוח חקירה — {_esc(data['case_name'])}</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 2em; color: #111; }}
  h1 {{ border-bottom: 3px solid #2563EB; padding-bottom: .3em; }}
  h2 {{ color: #2563EB; margin-top: 1.6em; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .9em; }}
  th, td {{ border: 1px solid #bbb; padding: 6px 8px; text-align: right; }}
  th {{ background: #eef2ff; }}
  .mono {{ font-family: monospace; font-size: .8em; direction: ltr; text-align: left; }}
  .meta {{ color: #555; font-size: .9em; }}
  @media print {{ h2 {{ page-break-after: avoid; }} }}
</style>
</head>
<body>
<h1>דוח חקירה — {_esc(data['case_name'])}</h1>
<p class="meta">הופק: {_esc(data['generated_at'])} · {_esc(data['tool'])} ·
כל פריט ראיה מזוהה ב-SHA256 לשמירת שרשרת משמורת.</p>

<h2>1. מצאי ראיות (שרשרת משמורת)</h2>
<table>
<tr><th>מזהה</th><th>שם קובץ</th><th>SHA256</th><th>גודל (בייטים)</th><th>סטטוס</th><th>נקלט</th></tr>
{rows_evidence}
</table>

<h2>2. ציר זמן</h2>
<table>
<tr><th>תאריך</th><th>ראיה</th><th>מיקום במקור</th><th>הקשר</th></tr>
{rows_timeline}
</table>

<h2>3. ישויות מרכזיות</h2>
<table>
<tr><th>ישות</th><th>סוג</th><th>מופעים</th></tr>
{rows_entities}
</table>

<h2>4. יומן פעולות (Audit Trail)</h2>
<table>
<tr><th>מועד</th><th>פעולה</th><th>ראיה</th></tr>
{rows_audit}
</table>

<p class="meta">מסמך זה הופק אוטומטית מתוך ראיות מאוחסנות בלבד. להדפסה כ-PDF: Ctrl+P.</p>
</body>
</html>"""


def generate_report(session: Session, case_id: int | None = None) -> dict:
    data = build_report_data(session, case_id)
    reports_dir = get_settings().evidence_store_dir.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = f"case_{case_id}" if case_id is not None else "all"
    path = reports_dir / f"report_{suffix}_{stamp}.html"
    path.write_text(render_html(data), encoding="utf-8")

    return {
        "path": str(path.resolve()),
        "case_name": data["case_name"],
        "evidence_count": len(data["evidence"]),
        "timeline_events": len(data["timeline"]),
        "entities": len(data["entities"]),
    }
