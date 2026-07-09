# CaseMind Defense Desktop v0.11 Starter

## Run

Start backend first:

```powershell
cd E:\WORK-FOLD\CaseMindDefense\backend
.\.venv\Scripts\activate
uvicorn app.main:app --reload
```

Then start desktop:

```powershell
cd E:\WORK-FOLD\CaseMindDefense\desktop\casemind_desktop
python main.py
```

## API expected

- GET /health
- GET /evidence
- POST /evidence/import-file
- GET /search/semantic
- POST /ai/ask
