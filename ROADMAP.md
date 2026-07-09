# Roadmap

| Version | Theme | Status |
|---------|-------|--------|
| v0.11 | Backend Hardening | ✅ Done |
| v0.12 | Desktop Workspace | 🔨 Current |
| v0.13 | AI Investigation Workspace | Planned |
| v0.14 | Reporting | Planned |
| v1.0 | Commercial Release | Planned |

## v0.12 — Desktop Workspace (current)

- 0.12.1: modular widget refactor, controller layer, background API workers, three-panel workspace, preview engine (TXT/images, PDF placeholder)
- 0.12.2: Semantic Search workspace
- 0.12.3: AI workspace
- 0.12.4: Timeline & Entity Graph views

## v0.13 — AI Investigation Workspace

- Local LLM (Ollama) RAG over indexed chunks — every answer cites `chars:start-end`, "not found" when evidence is missing
- Bilingual embedding model (e.g. multilingual-e5)
- Hebrew NER (DictaBERT) replacing regex entities
- Contradiction detection: semantic pairing + NLI/LLM verdict

## v0.14 — Reporting

- Case reports with citation navigation
- Export (PDF/DOCX) with chain-of-custody appendix

## v1.0 — Commercial Release

- Installer, backup/recovery, auth + permissions, monitoring, plugin system, full docs

## Cross-cutting backlog

- `Case` entity (multi-case separation) — earlier is cheaper
- FTS5 (keyword) + sqlite-vec (semantic) — stop scanning chunks in Python
- Background indexing pipeline with live status
- API key + path validation on import endpoints
- Verify Hebrew text-layer PDFs against pypdf RTL issue (py-pdf/pypdf#1589)
