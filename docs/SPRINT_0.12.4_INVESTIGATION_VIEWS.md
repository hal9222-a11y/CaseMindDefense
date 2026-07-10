# Sprint 0.12.4 — Investigation Views

## Goal

No placeholder pages left: Timeline, Entities, and Contradictions show
real case data with navigation into the evidence.

## Deliverables

- Backend: entities carry a `type` (name / hebrew_term / phone /
  israeli_id / vehicle_plate)
- `DataTableWidget` + generic `DataPage` (lazy-loads on first open)
- Timeline page: normalized date, as-written date, source, snippet;
  double-click opens the evidence with the snippet highlighted
- Entities page: entity / type / count; double-click runs a keyword
  search for the entity
- Contradictions page: marked experimental until the v0.13 engine

## Definition of Done

- All sidebar pages except Settings show live data
- Timeline double-click lands on the right evidence
- Entity double-click shows its occurrences in search
- Backend tests green; CI green
