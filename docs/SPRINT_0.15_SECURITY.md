# Sprint 0.15 — Security & Packaging

## Delivered (part 1 — security layer)

- **API key auth**: set `CASEMIND_API_KEY` on backend and desktop —
  every endpoint except `/health` then requires `X-API-Key`
  (constant-time compare). Unset = open localhost dev mode.
- **Import path allowlist**: `CASEMIND_IMPORT_ROOTS` (os.pathsep-
  separated) restricts imports to allowed trees → 403 outside; blocks
  using the API to read arbitrary system files.
- **Tamper detection**: `POST /admin/verify-evidence` re-hashes every
  stored file against its recorded SHA256; reports verified / missing /
  tampered; audited.
- **Backup**: `POST /admin/backup` — consistent SQLite snapshot (sqlite
  backup API, safe while running) + evidence store in one zip. Restore
  is manual by design (unzip and place back) — no auto-restore footgun.
- **Desktop Settings page** (last placeholder gone): connection + key
  status, Verify Integrity and Create Backup buttons with results.

## Delivered (part 2 — install path)

- **Backend auto-start**: the desktop app checks `/health` on launch and
  starts the backend itself (hidden, survives app close so restarts are
  instant); clear guidance dialog if the venv is missing. Verified live:
  backend down → app alone → backend answering within ~2s.
- **`scripts/setup.ps1`**: one-shot clean-machine setup — Python via
  winget if missing, both venvs + deps, Tesseract (UB Mannheim, Hebrew
  note), optional Ollama + model pull, Desktop shortcut running
  `pythonw` (no console window).
- **File logging**: rotating `data/logs/backend.log` (2MB ×3).
- **PyInstaller deliberately skipped**: torch/transformers make a
  multi-GB brittle bundle; a venv-based install with a shortcut is
  robust and updatable (`git pull` + rerun setup). Revisit only if
  pilot users can't run a .ps1.

## Remaining in v0.15

- Encryption at rest (evaluate: SQLCipher vs OS-level BitLocker guidance)

## Verified

- 47/47 tests ×2+ (auth on/off, allowlist 403, tampering detected on a
  modified stored file, backup zip contents)
- Live: integrity OK over real store; 8.6 MB backup zip created
