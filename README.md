# CaseMind Defense v0.10-alpha Recovery

This package recreates the current CaseMind Defense project after data loss.

## Includes

- FastAPI backend
- SQLModel + SQLite
- Evidence import by file/folder path
- SHA256 duplicate detection
- Audit log
- TXT/PDF text extraction
- Image OCR via Tesseract/pytesseract
- Chunking with `chars:start-end` citation offsets
- Sentence Transformers embeddings with deterministic fallback
- Semantic Search endpoint
- AI Ask endpoint with evidence citations
- Entities / Timeline / Contradictions endpoints
- PySide6 Desktop client
- Test suite

## Install Backend

```powershell
cd E:\WORK-FOLD\CaseMindDefense\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
pytest
python -m uvicorn app.main:app --reload
```

## Install Desktop

```powershell
cd E:\WORK-FOLD\CaseMindDefense\desktop
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m casemind_desktop.main
```
