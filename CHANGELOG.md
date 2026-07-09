# Changelog

## Unreleased (sprint 0.12.1 — Desktop Workspace)

- Removed dead duplicate desktop API client (`api_client.py`)
- `/ai/ask` accepts `limit` (1–20, default 5)
- Text search runs in SQL (LIKE) instead of scanning all chunks in memory
- Timeline events return a ±150-char snippet around the date instead of the full chunk
- Scanned-PDF OCR capped at `CASEMIND_PDF_OCR_MAX_PAGES` (default 50) pages per file
- Fixed phone entity regex never matching `+972` numbers
- Rewrote `ARCHITECTURE.md` (was broken escaped markdown), filled `ROADMAP.md` and this changelog

## v0.11 — Backend Hardening

- Fixed PDF pages joined with literal `\n` instead of newline
- Exact `chars:start-end` citation offsets (computed on original text, chunks stored unstripped)
- Timeline: ISO date normalization + chronological sorting
- Hebrew entity extraction (tokens + stopwords, phones, IDs, vehicle plates)
- Embedding fallback dimension 384 (matches MiniLM); per-chunk `embedding_model` / `embedding_dimension` / `embedding_version` metadata with auto column migration
- Scanned-PDF OCR fallback via pypdfium2 + Tesseract (`eng+heb`); new statuses `ocr_indexed` / `extraction_not_supported`
- Real FK `EvidenceChunk.evidence_id → evidence.id`
- `limit`/`offset` pagination on `/evidence`, `/audit`, `/timeline`, `/entities`
- Test isolation fixed (settings read env at instantiation); suite passes repeatedly with a dev DB present
- Semantic search: dimension-mismatch chunks skipped with a warning; Evidence lookups cached

## v0.10-alpha

Recovery package after data loss:

- Evidence import (file/folder), SHA256 duplicate detection
- OCR (Tesseract), PDF/TXT extraction, chunking with citation offsets
- Embeddings + semantic search, Evidence AI with citations
- Entities / Timeline / Contradictions endpoints, audit trail
- PySide6 desktop shell, test suite
