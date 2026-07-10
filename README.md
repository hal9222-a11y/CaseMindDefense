# CaseMind Defense

Local-first **Investigation Intelligence Platform** — secure evidence management with automatic analysis, OCR (Hebrew + English), semantic search, and evidence-grounded AI answers with exact citations.

Built for defense lawyers, investigators, and enforcement teams. All data stays on your machine.

- 📖 [User Guide (עברית)](docs/USER_GUIDE.md) · [Vision](docs/VISION.md) · [Architecture](ARCHITECTURE.md) · [Security Model](docs/SECURITY.md) · [Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md)
- 🏷️ Current release: **v0.15.0** — MVP + reporting + security. Next: [v1.0](ROADMAP.md)
- ⚡ Quick install on a clean machine: `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`

## Features

- Evidence import (files/folders) with SHA256 duplicate detection and content-addressed storage
- Full audit trail (chain of custody)
- Text extraction: TXT, PDF (native text layer), scanned PDFs and images via Tesseract OCR (`eng+heb`)
- Chunking with exact `chars:start-end` citation offsets
- Semantic search (SentenceTransformers) + keyword search
- AI Ask endpoint answering only from stored evidence, with citations
- Entities, timeline, and contradiction endpoints
- PySide6 desktop client

## Backend — install & run

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
pytest
python -m uvicorn app.main:app --reload
```

Requires [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) with the `heb` language pack (auto-detected; override with `TESSERACT_CMD`).

## Desktop — install & run

```powershell
cd desktop
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m casemind_desktop.main
```

## Configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `CASEMIND_DATABASE_URL` | `sqlite:///./casemind_defense.db` | Backend database |
| `CASEMIND_EVIDENCE_STORE` | `./data/evidence_store` | Evidence file store |
| `CASEMIND_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| `CASEMIND_PDF_OCR_MAX_PAGES` | `50` | OCR page cap per scanned PDF |
| `CASEMIND_BACKEND_URL` | `http://127.0.0.1:8000` | Desktop → backend URL |

> ⚠️ The backend has no authentication yet — keep it bound to `127.0.0.1`.
