from __future__ import annotations

import os
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.settings import get_settings
from app.db import get_session
from app.models.evidence import Evidence
from app.services.audit_service import log_event, verify_audit_chain
from app.services.hash_service import sha256_file

router = APIRouter(prefix="/admin", tags=["admin"])


def _drive_of(path: str) -> str:
    r"""The root a path lives under, so paths from different drives are grouped
    apart: '\\server\share' for UNC, 'D:' for local."""
    if path.startswith("\\\\") or path.startswith("//"):
        parts = path.replace("/", "\\").split("\\")
        return "\\\\" + "\\".join(parts[2:4])  # \\server\share
    return path[:2]


class BackgroundRequest(BaseModel):
    enabled: bool


@router.post("/background")
def set_background(req: BackgroundRequest):
    """Turn background material processing (translation + re-indexing) on or off
    at runtime. Pausing takes effect between files — whatever is mid-process
    finishes, nothing new starts. Not persisted: a restart resumes working."""
    from app.services import background_control

    background_control.set_paused(not req.enabled)
    return {"background_enabled": req.enabled}


@router.get("/source-root")
def source_root(session: Session = Depends(get_session)):
    """The folder most of the evidence was imported FROM. Shown so the user can
    re-point it after moving the files. Evidence can come from several drives;
    we report the one holding the most files (the folder most worth re-pointing)."""
    paths = [p for p in session.exec(select(Evidence.original_path)).all() if p]
    if not paths:
        return {"root": "", "count": 0}

    groups: dict[str, list[str]] = {}
    for p in paths:
        groups.setdefault(_drive_of(p), []).append(p)
    biggest = max(groups.values(), key=len)
    try:
        root = os.path.commonpath(biggest)
    except ValueError:
        root = os.path.dirname(biggest[0])
    return {"root": root, "count": len(biggest), "total": len(paths)}


class RelocateRequest(BaseModel):
    old_prefix: str
    new_prefix: str


@router.post("/relocate-source")
def relocate_source(req: RelocateRequest, session: Session = Depends(get_session)):
    """Re-point the recorded source folder after the evidence was moved to a new
    location (e.g. a network share copied to a local disk). Only the recorded
    original_path is rewritten — the files themselves already live in the app's
    local store, so nothing is copied or moved. Makes the Inspector accurate and
    future re-imports read from the fast path.
    """
    old = req.old_prefix.rstrip("/\\")
    new = req.new_prefix.rstrip("/\\")
    if not old or not new:
        raise HTTPException(status_code=422, detail="old and new folder are required")

    def under(path: str) -> bool:
        # match at a folder boundary, not any character: old="C:\case" must NOT
        # match "C:\case2\..." or "C:\caseX" and corrupt their paths
        return path == old or path.startswith(old + "\\") or path.startswith(old + "/")

    rows = session.exec(select(Evidence)).all()
    updated = 0
    for ev in rows:
        if ev.original_path and under(ev.original_path):
            ev.original_path = new + ev.original_path[len(old):]
            session.add(ev)
            updated += 1
    session.commit()
    log_event(session, "source_relocated", old=old, new=new, updated=updated)
    return {"updated": updated, "old": old, "new": new}


@router.post("/verify-audit")
def verify_audit(session: Session = Depends(get_session)):
    """Audit-log tamper detection: recomputes the event hash chain."""
    return verify_audit_chain(session)


@router.post("/reindex-all")
def reindex_all(background: BackgroundTasks, session: Session = Depends(get_session)):
    """Re-run the whole analysis over material that is already imported.

    Needed when the analysis itself changes — extracting the conversation
    participants, real Russian NER, validated phone numbers. Evidence indexed by
    the older pipeline keeps its old (worse) entities until it is re-read.

    Marks everything as pending and lets the existing sequential background
    indexer work through it, so the app stays usable while it runs.
    """
    from app.services.evidence_service import resume_pending_indexing

    evidence = session.exec(
        select(Evidence).where(Evidence.status.not_in(("processing", "imported")))
    ).all()
    for item in evidence:
        item.status = "processing"
        session.add(item)
    session.commit()

    background.add_task(resume_pending_indexing)
    return {"queued": len(evidence), "status": "reindexing started"}


@router.post("/reindex-pending")
def reindex_pending(background: BackgroundTasks, session: Session = Depends(get_session)):
    """Re-queue every evidence stuck in 'processing' (orphaned by a crash or
    a killed background task). Runs sequentially in the background."""
    from app.services.evidence_service import resume_pending_indexing

    pending = session.exec(
        select(Evidence.id).where(Evidence.status == "processing")
    ).all()
    background.add_task(resume_pending_indexing)
    return {"pending": len(pending), "status": "reindexing started"}


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
