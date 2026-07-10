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

## Remaining in v0.15

- PyInstaller installer (desktop auto-starts backend; Tesseract/Ollama
  guided install)
- Structured file logging
- Encryption at rest (evaluate: SQLCipher vs OS-level BitLocker guidance)

## Verified

- 47/47 tests ×2+ (auth on/off, allowlist 403, tampering detected on a
  modified stored file, backup zip contents)
- Live: integrity OK over real store; 8.6 MB backup zip created
