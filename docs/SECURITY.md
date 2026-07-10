# CaseMind Defense — Security Model

Local-first by design: case material never leaves the machine. This
document is the current, honest state of each protection layer.

## Layers

| Layer | Mechanism | Status |
|-------|-----------|--------|
| Transport | Backend binds `127.0.0.1` only | ✅ default |
| Authentication | `CASEMIND_API_KEY` → `X-API-Key` on every endpoint except `/health` (constant-time compare) | ✅ opt-in |
| Import containment | `CASEMIND_IMPORT_ROOTS` allowlist → 403 outside | ✅ opt-in |
| Evidence integrity | Content-addressed store + SHA256 per file; `POST /admin/verify-evidence` re-hashes everything | ✅ |
| Audit integrity | Hash chain over the audit log (`prev_hash`/`event_hash`); `POST /admin/verify-audit` detects any rewrite of history | ✅ |
| Backup | `POST /admin/backup` — consistent SQLite snapshot + evidence store in one zip; restore manual by design | ✅ |
| AI privacy | LLM (Ollama), embeddings, NER — all local; zero cloud calls with case content | ✅ |

## Encryption at rest — decision

**Recommendation: OS-level full-disk encryption (BitLocker), not
app-level SQLCipher.**

Rationale:
- BitLocker protects *everything* the app writes — DB, evidence store,
  reports, backups, logs — with zero code and OS-grade key management.
  SQLCipher would cover only the DB file, leaving the evidence store
  (the actual case files) unprotected unless we build file encryption
  too, plus key-entry UX, plus a migration.
- Threat model: a lawyer's stolen/lost laptop. BitLocker answers it
  fully. An attacker with a *running, unlocked* session defeats
  app-level encryption as well.

Setup guidance for pilots: enable BitLocker on the drive holding the
repo (`Manage BitLocker` → Turn on), store the recovery key outside the
machine. Revisit SQLCipher only if a customer requires per-file
encryption with the OS layer unavailable.

## Known limits (deliberate, tracked)

- Single-user: no roles/permissions until multi-user demand is real (v1.0 gate)
- Audit chain assumes a single writer (local app); serialize writers before multi-user
- No TLS: loopback-only traffic; add a reverse proxy if the backend is ever exposed
