# Sprint 0.12.2 — Search Workspace

## Goal

Find anything in the case and jump straight to the evidence.

## Deliverables

- Search mode toggle: Semantic / Keyword (both backend endpoints exist)
- Citation navigation: clicking a search result or an AI citation opens
  the Evidence page with the row selected and the cited chunk
  highlighted in the preview
- Shared navigation path used by both SearchPage and AIPage

## Definition of Done

- Type a phrase from an imported Hebrew document → result appears in
  both modes → click → Evidence page opens on that document with the
  chunk visible
- Backend tests still green; CI green
