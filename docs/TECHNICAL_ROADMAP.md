# Technical Roadmap — Execution Plan to v1.0

Written 2026-07-10, after sprint 0.12.1 core landed. Companion to
[VISION.md](VISION.md) (the "why") and [ROADMAP.md](../ROADMAP.md) (the
one-page version). This is the "how and in what order".

## Definition of project MVP

> A single defense lawyer runs one criminal case with 200–500 scanned
> Hebrew documents end-to-end: import, search, ask the AI, get cited
> answers — locally, with every claim traceable to `chars:start-end`.

Everything below is sequenced to reach that MVP first (v0.13), then
commercial readiness (v1.0).

## Where we stand (honest status vs the 10 vision goals)

| # | Vision goal | Status | Gap |
|---|-------------|--------|-----|
| 1 | Evidence repository | 🟢 80% | No Case entity, no tags/manual metadata |
| 2 | Automatic extraction | 🟢 75% | Entities are regex-level; docx/eml unsupported |
| 3 | Advanced search | 🟡 50% | No entity/date/source filters; semantic scans in Python |
| 4 | AI assistant | 🔴 20% | Returns cited chunks; no LLM answer synthesis |
| 5 | Investigation picture | 🟡 30% | Timeline API only; no graph; desktop views missing |
| 6 | Legal admissibility | 🟡 60% | No tamper re-verification, no signatures |
| 7 | Local & secure | 🟢 85% | No auth on API; no encryption at rest |
| 8 | Professional workspace | 🟡 45% | Evidence workspace done; 4 pages still placeholders |
| 9 | Performance & scale | 🔴 15% | In-memory scans; sync indexing in request path |
| 10 | Commercial product | 🔴 5% | No installer/backup/permissions |

## Sprint sequence

### 0.12.1 — Desktop Workspace Foundation (close-out, ~1 day)
Core landed (widgets, controller, async workers, preview engine).
Remaining:
- [ ] Manual QA pass: select rows → preview/inspector update; import → table refresh
- [ ] Search + AI pages rebuilt on the widget pattern (result table widget shared)
- [ ] DoD: app fully usable with mouse only, no freezes, 21/21 backend tests

### 0.12.2 — Search Workspace (~3 days)
- Keyword + semantic toggle in one page; results show filename, score, citation
- "Open in Evidence" navigation: result row → Evidence page with row selected, preview showing the cited chunk
- Backend: `/search` gains `mode=keyword|semantic` (or keep two endpoints, one UI)
- DoD: find a phrase in an imported Hebrew PDF and jump to its evidence

### 0.12.3 — AI Workspace (~2 days)
- Question box + cited-answer view; citations rendered as clickable rows (same navigation as search)
- Uses today's retrieval-only `/ai/ask` — UI must not assume an LLM yet
- DoD: ask → citations listed → click-through to evidence

### 0.12.4 — Timeline & Entities views (~3 days)
- Timeline page: table of events (date, snippet, source) sorted, click-through
- Entities page: entity/type/count table with occurrences drill-down
- Contradictions page: honest "experimental" table over the placeholder endpoint
- DoD: all sidebar pages show real data; zero placeholder pages left

### 0.12.5 — Data model & scale foundation (~1–2 weeks) ⚠️ new, not in original roadmap
The engineering debt that must land **before** the AI sprint doubles data volume:
- **Case entity**: `case_id` on Evidence (+ API filter + case picker in desktop). Cheapest now, painful later
- **FTS5** virtual table for keyword search (replaces LIKE)
- **sqlite-vec** for embeddings (replaces CSV strings + Python cosine loop)
- **Background indexing**: import returns immediately with `status=processing`; a worker (FastAPI BackgroundTasks is enough at this scale) does extract→chunk→embed; desktop polls status
- **Reindex endpoint** for embedding model migrations (metadata already in place)
- DoD: import a 300-file folder without blocking; search stays <1s at 100k chunks

### v0.13 — AI Investigation Workspace (~2–3 weeks) → **MVP**
- **Ollama integration**: local LLM synthesizes answers from retrieved chunks. Hard contract: every sentence cites `chars:start-end`; no evidence → "not found". Graceful degradation to citation-only mode when Ollama absent
- **Bilingual embeddings**: switch default to multilingual-e5 (env var exists); reindex path already built in 0.12.5
- **Hebrew NER**: DictaBERT replaces regex entities (keep regex for phones/IDs/plates — those work)
- **Contradiction engine v1**: candidate pairs by semantic similarity → NLI/LLM verdict; replaces yes/no placeholder
- **Entity graph**: co-occurrence graph (entities sharing evidence), rendered in desktop
- DoD = **the MVP statement above, demonstrated on a real case folder**

### v0.14 — Reporting (~1–2 weeks)
- Report builder: selected evidence/answers/timeline into a structured report
- Export DOCX/PDF with citation appendix + chain-of-custody (SHA256, import log per item)
- DoD: court-shareable document generated from a case in one action

### v0.15 — Security & packaging (~2 weeks) ⚠️ new, split out of v1.0
- API key auth (backend generates, desktop stores) + import path allowlist
- Tamper detection: scheduled re-hash of evidence store vs DB
- Backup/restore (DB + evidence store, one archive)
- Installer: PyInstaller bundle — desktop auto-starts/starts backend; Tesseract bundled or guided install
- Structured logging + crash reporting (local file)
- DoD: non-developer installs on a clean Windows machine and imports a case

### v1.0 — Commercial release (~2–4 weeks)
- Permissions/multi-user (if actually needed by first customers — validate first)
- Digital signatures on audit events (goal 6, "future")
- Full user + API docs, licensing/activation decision
- Plugin architecture: **recommend deferring past 1.0** unless a concrete plugin exists
- DoD: first paying/pilot user works a real case unassisted

## Cross-cutting rules (every sprint)

1. Branch per sprint → PR → merge to main; push at least daily (E: drive has disconnected twice)
2. Tests run twice before every commit; new logic ships with a test
3. CHANGELOG + ROADMAP updated at sprint close
4. Any AI output without a citation is a bug, not a feature request

## Top risks

| Risk | Mitigation |
|------|-----------|
| RTL extraction variance across PDF producers | Final-letter heuristic is in; collect real court PDFs as fixtures each sprint |
| Ollama quality/hardware on user machines | Citation-only fallback mode is mandatory forever |
| Scale targets (goal 9: millions of chunks) | 0.12.5 gets to ~100k chunks; millions = post-1.0 (Postgres/pgvector path documented, not built) |
| Single developer + single machine | Remote pushed on every sprint; consider enabling GitHub Actions CI (15-min task, still pending) |
| Scope creep toward goal-10 features | MVP statement gates every sprint: does it serve the one-lawyer-one-case story? |

## Immediate next actions (this week)

1. Close 0.12.1: manual QA + widgetize Search/AI pages
2. Add GitHub Actions CI (pytest on push) — catches breakage the day it happens
3. Delete duplicate `master` branch; `gh auth login` once
4. Start 0.12.2
