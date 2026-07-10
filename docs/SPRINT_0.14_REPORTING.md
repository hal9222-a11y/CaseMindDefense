# Sprint 0.14 — Reporting

## Goal

One action turns a case into a court-shareable document.

## Delivered (part 1)

- `report_service`: gathers case header, evidence inventory with SHA256
  (chain of custody), case-scoped timeline, top entities, and the audit
  trail; renders a self-contained RTL Hebrew HTML report
- `POST /reports {case_id?}` writes `data/reports/report_*.html`,
  audited as `report_generated`
- Desktop: Report button in the Evidence toolbar — generates for the
  selected case (or all) and opens the report in the browser; Ctrl+P
  prints to PDF with correct Hebrew (browsers do bidi natively)

## Design decision

HTML-first instead of DOCX/PDF libraries: zero new dependencies, perfect
RTL for free, print-to-PDF built into every browser. DOCX export lands
in part 2 if editing-in-Word demand shows up (python-docx + w:bidi).

## Verified

- 42/42 tests ×2 (case-scoped report content: filename, SHA256,
  timeline date, RTL; all-cases smoke)
- Live report over the real case data: custody chain, hashes, RTL ✓
