# Changelog

## Unreleased

- **Persons ("who is who")**: a per-case people view. Each person has a
  name and a description of who they are, and can carry aliases/nicknames,
  phone numbers, photo links (to image evidence), and typed relations to
  other people (e.g. brother, father of, close friend). People who don't
  appear in the materials can be added manually. `/persons` CRUD + links;
  a Persons page in the sidebar. Deleting a person or a case removes their
  people and links

- Delete a whole case when a matter is closed: `DELETE /cases/{id}`
  removes the case and every piece of its evidence (files, chunks,
  entities, index); a red "Delete Case" button on the Evidence toolbar
  (enabled only for a selected case) with a strong confirmation dialog

- **Case-scoped analysis**: search, semantic search, AI ask, timeline,
  entities, entity graph and contradictions now respect the selected
  case — one client's material no longer bleeds into another's views.
  Selecting a case on the Evidence page scopes every analysis view; the
  analysis endpoints take an optional `case_id` (default = all cases)

- Audio/video evidence is transcribed locally (faster-whisper) in the
  background: wiretaps and interrogation videos become searchable with
  time-range citations (`time:MM:SS-MM:SS`); statuses `transcribed` /
  `transcription_unavailable`. Hebrew-tuned model (ivrit.ai) recommended
  via `CASEMIND_WHISPER_MODEL`
- Russian support: OCR language packs auto-detected (app-managed
  tessdata with heb+rus), Cyrillic entity extraction, cross-lingual
  search verified (Hebrew query -> Russian scanned document)

## v0.15.0 — 2026-07-10 · Security & Install Path

- Desktop auto-starts the backend on launch (no more manual uvicorn)
- `scripts/setup.ps1`: one-shot clean-machine install (Python, venvs,
  Tesseract, optional Ollama, Desktop shortcut)
- Backend logs to rotating `data/logs/backend.log`

- API key auth (`CASEMIND_API_KEY` + `X-API-Key`, `/health` exempt)
- Import path allowlist (`CASEMIND_IMPORT_ROOTS`) → 403 outside
- Tamper detection: `POST /admin/verify-evidence` re-hashes the store
- One-zip backup: `POST /admin/backup` (consistent SQLite snapshot)
- Desktop Settings page replaces the last placeholder (key status,
  integrity check, backup)

## v0.14 — 2026-07-10 · Reporting

- Case reports: `POST /reports` renders a self-contained RTL Hebrew HTML
  report — evidence inventory with SHA256 chain of custody, case
  timeline, top entities, audit trail; desktop Report button generates
  and opens it (Ctrl+P → PDF)

## v0.13 — 2026-07-10 · AI Investigation Workspace (MVP)

- Entity co-occurrence graph (`/entities/graph` + desktop page: circle
  layout, node size by mentions, color by type, double-click searches)
- Case picker in the Evidence toolbar (filter, import into case, create)
- AI page shows the answer mode and model

- Real contradiction engine: semantically similar chunk pairs across
  different evidence are judged by the local LLM; consistent pairs are
  dropped, contradictions come with an explanation; without an LLM the
  top pairs are returned as `unverified`. Desktop page shows verdict /
  files / similarity / explanation and double-click opens evidence A

- Hebrew NER via DictaBERT: entities extracted at index time into an
  `extractedentity` table (person / organization / location / time +
  deterministic phone / ID / plate patterns), aggregated by `/entities`;
  regex fallback when the model is unavailable; reindex replaces entities

- Default embedding model switched to `intfloat/multilingual-e5-small`
  (Hebrew + English in one vector space; Hebrew queries now match
  English evidence and vice versa) with e5 `query:`/`passage:` prefixes
- Semantic search skips chunks embedded with a different model (same
  dimension ≠ same space) and logs a reindex hint

- `/ai/ask` synthesizes answers with a local LLM via Ollama (default
  `qwen2.5:3b-instruct`), grounded only in stored evidence with `[n]`
  citation markers; response carries `mode` and `model`
- Graceful degradation: no Ollama / model failure → citation-only mode
  (previous behavior), never an error
- Small-model artifact cleanup and question-language pinning (Hebrew
  answers stay Hebrew)

## v0.12.5 — 2026-07-10 · Scale Foundation

- Case entity: create/list cases, import into a case, filter evidence by case
- Imports return immediately (`processing`) and index in the background;
  `GET /evidence/{id}` polls status; `POST /evidence/{id}/reindex` rebuilds chunks
- Keyword search served by SQLite FTS5 (trigger-synced, LIKE fallback)

## v0.12.4 — 2026-07-10 · Investigation Views

- Timeline, Entities, and Contradictions pages show live data (no
  placeholders left except Settings); pages lazy-load on first open
- Entities carry a type (name / hebrew_term / phone / israeli_id /
  vehicle_plate); double-clicking an entity searches its occurrences
- Timeline double-click opens the evidence with the snippet highlighted
- Contradictions page marked experimental until the v0.13 engine

## v0.12.2 — 2026-07-10 · Search Workspace

- Search mode toggle: Semantic / Keyword in one search page
- Citation navigation: double-clicking a search result or AI citation
  opens the Evidence page with the row selected and the cited chunk
  highlighted in the text preview; PDF citations show the cited excerpt
  until real PDF rendering lands

## v0.12.1 — 2026-07-10 · Desktop Workspace

- Search and AI pages rebuilt on the widget pattern with a shared results
  table (`ResultsTableWidget`) — ready for citation navigation in 0.12.2;
  AI page now shows answer and citations in separate panes; Enter runs search
- GitHub Actions CI: backend tests (with Hebrew Tesseract) + desktop
  compile check on every push

- **Hebrew PDFs extract correctly**: PDF text extraction moved from pypdf (dropped Hebrew glyphs entirely) to pypdfium2, with automatic visual-vs-logical order detection (final-letter heuristic) and bidi correction only when needed — verified against a real court document and a generated visual-order PDF
- **Desktop no longer freezes**: all API calls (health check, evidence load, import, semantic search, AI ask) run on background workers; buttons disable during in-flight requests

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
