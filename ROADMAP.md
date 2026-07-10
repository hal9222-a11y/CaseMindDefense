# Roadmap

| Version | Theme | Status |
|---------|-------|--------|
| v0.11 | Backend Hardening | ✅ Done |
| v0.12 | Desktop Workspace | ✅ Done |
| v0.13 | AI Investigation Workspace (MVP) | ✅ Done |
| v0.14 | Reporting | ✅ Done |
| v0.15 | Security & Install Path | ✅ Done (tag `v0.15.0`) |
| v1.0 | Commercial Release | 🔨 Current |

## v1.0 — Commercial Release (current)

Gate: a real pilot. Build only what pilot users actually hit.

- **MVP acceptance test**: a real criminal case (hundreds of scanned
  Hebrew documents) end to end — findings drive the rest of v1.0
- Permissions / multi-user — only if a pilot needs it
- Licensing / activation decision
- Polish from pilot feedback

## Cross-cutting backlog

- sqlite-vec KNN for semantic search and contradiction pairing
  (Python scan fine below ~100k chunks)
- DOCX report export (if lawyers need to edit reports in Word)
- Contradictions page progress indicator (first load runs LLM ~2 min)
- Alembic when schema churn outgrows naive ALTER migrations
- Entity cleanup: strip ב/ל prefixes from locations, drop subword-broken names
- Plugin architecture — post-1.0 unless a concrete plugin appears

## Done highlights

- Hebrew end-to-end: OCR (eng+heb), RTL-correct PDF extraction with
  visual/logical detection, DictaBERT NER, bilingual e5 embeddings,
  Hebrew LLM answers with citations — all local
- Legal admissibility: SHA256 chain of custody, tamper detection for
  files and for the audit log (hash chain), one-zip backup, case reports
- Scale foundation: FTS5, background indexing, reindex path, Case entity
