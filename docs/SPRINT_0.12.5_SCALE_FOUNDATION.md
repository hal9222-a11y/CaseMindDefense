# Sprint 0.12.5 — Data Model & Scale Foundation

## Goal

The engineering groundwork that must land before v0.13 doubles data
volume: multi-case separation, non-blocking imports, real search index.

## Delivered

- **Case entity**: `/cases` (create/list), `case_id` on import (file &
  folder) and as a filter on `GET /evidence`; column migration for
  existing DBs
- **Background indexing**: import registers evidence (hash, dedupe,
  copy) and returns immediately with `status=processing`; extraction,
  chunking, and embedding run as a background task; `GET /evidence/{id}`
  for status polling
- **FTS5 keyword search**: `chunk_fts` virtual table synced by triggers,
  one-time rebuild for existing DBs, phrase-quoted MATCH with graceful
  LIKE fallback on SQLite builds without FTS5
- **Reindex**: `POST /evidence/{id}/reindex` — chunks are replaced
  (embedding-model migrations use this path)

## Deferred

- sqlite-vec for semantic search: Python cosine scan remains the
  fallback and is adequate below ~100k chunks; wire vec0 when a real
  case corpus shows the need
- Desktop case picker UI — next desktop sprint

## Verified

- 25/25 tests, run twice
- Live: Hebrew-named case created; import into case returns
  `processing` and lands `indexed` after the background task; FTS
  serves Hebrew keyword queries against a real court PDF
