from __future__ import annotations

import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.core.settings import get_settings
from app.db import get_session
from app.models.evidence import Evidence
from app.services.audit_service import log_event
from app.services.hash_service import sha256_file

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/verify-evidence")
def verify_evidence(session: Session = Depends(get_session)):
    """Tamper detection: re-hash every stored file against the recorded
    SHA256. Any mismatch means the evidence store was modified."""
    verified, missing, tampered = 0, [], []

    for ev in session.exec(select(Evidence)).all():
        stored = Path(ev.stored_path)
        if not stored.exists():
            missing.append({"id": ev.id, "filename": ev.filename})
            continue
        actual = sha256_file(stored)
        if actual != ev.sha256:
            tampered.append(
                {"id": ev.id, "filename": ev.filename, "expected": ev.sha256, "actual": actual}
            )
        else:
            verified += 1

    result = {
        "verified": verified,
        "missing": missing,
        "tampered": tampered,
        "ok": not missing and not tampered,
    }
    log_event(
        session, "integrity_check",
        verified=verified, missing=len(missing), tampered=len(tampered),
    )
    return result


@router.post("/backup")
def create_backup(session: Session = Depends(get_session)):
    """One-file backup: consistent SQLite snapshot (sqlite backup API,
    safe while the app runs) + the evidence store, zipped.

    Restore is manual by design: unzip and put the files back — an
    automatic restore endpoint overwriting a live DB is a footgun."""
    settings = get_settings()
    store_dir = settings.evidence_store_dir
    backups_dir = store_dir.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_path = backups_dir / f"casemind_backup_{stamp}.zip"

    db_url = settings.database_url
    db_file = Path(db_url.replace("sqlite:///", "", 1))
    db_snapshot = backups_dir / f"db_snapshot_{stamp}.sqlite"

    src = sqlite3.connect(str(db_file))
    dst = sqlite3.connect(str(db_snapshot))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    files = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_snapshot, "casemind_defense.db")
        if store_dir.exists():
            for f in sorted(store_dir.rglob("*")):
                if f.is_file():
                    zf.write(f, Path("evidence_store") / f.relative_to(store_dir))
                    files += 1
    db_snapshot.unlink()

    result = {
        "path": str(zip_path.resolve()),
        "evidence_files": files,
        "size_bytes": zip_path.stat().st_size,
    }
    log_event(session, "backup_created", path=result["path"], evidence_files=files)
    return result
