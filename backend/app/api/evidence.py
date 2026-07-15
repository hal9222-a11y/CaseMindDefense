from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models.evidence import Evidence
from app.services.audit_service import log_event
from app.services.evidence_service import (
    SUPPORTED_EXTENSIONS,
    DuplicateEvidenceError,
    ImportPathNotAllowedError,
    delete_evidence_record,
    register_evidence,
)

router = APIRouter(prefix="/evidence", tags=["evidence"])


class ImportFileRequest(BaseModel):
    path: str
    case_id: int | None = None


class ImportFolderRequest(BaseModel):
    path: str
    case_id: int | None = None


def _evidence_dict(ev: Evidence) -> dict:
    return {
        "id": ev.id,
        "case_id": ev.case_id,
        "original_path": ev.original_path,
        # absolute: the desktop opens this file itself and runs from a different
        # working directory, so a backend-relative path resolves to nothing
        # there. Rows imported before the store path was absolute are fixed here
        # too, without a migration.
        "stored_path": str(Path(ev.stored_path).resolve()),
        "filename": ev.filename,
        "sha256": ev.sha256,
        "size_bytes": ev.size_bytes,
        "mime_type": ev.mime_type,
        "imported_at": ev.imported_at.isoformat(),
        "status": ev.status,
    }


def _index_in_background() -> None:
    # All indexing funnels through resume_pending_indexing: it serializes on one
    # process-wide lock (the ML models are not safe under concurrent inference)
    # and works through every evidence in 'processing', so a folder import that
    # lands while the startup resume is still running joins that queue instead
    # of racing it with a second model-inference loop.
    from app.services.evidence_service import resume_pending_indexing

    resume_pending_indexing()


@router.get("")
def list_evidence(
    # a forensic export runs to thousands of files; a low ceiling silently drops
    # evidence off the end of the browser, which is not acceptable in a legal tool
    limit: int = Query(100, ge=1, le=20000),
    offset: int = Query(0, ge=0),
    case_id: int | None = Query(None),
    session: Session = Depends(get_session),
):
    query = select(Evidence)
    if case_id is not None:
        query = query.where(Evidence.case_id == case_id)
    return session.exec(query.order_by(Evidence.id).offset(offset).limit(limit)).all()


@router.get("/{evidence_id}")
def get_evidence(evidence_id: int, session: Session = Depends(get_session)):
    ev = session.get(Evidence, evidence_id)
    if not ev:
        raise HTTPException(status_code=404, detail="evidence not found")
    return _evidence_dict(ev)


@router.post("/import-file")
def import_file_endpoint(
    req: ImportFileRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    try:
        ev = register_evidence(session, req.path, case_id=req.case_id)
    except DuplicateEvidenceError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "duplicate", "existing_id": exc.existing_id},
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="file not found")
    except ImportPathNotAllowedError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    background.add_task(_index_in_background)
    return _evidence_dict(ev)


@router.post("/import-folder")
def import_folder_endpoint(
    req: ImportFolderRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    root = Path(req.path).resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail="folder not found")

    # Never drop a file in silence. A forensic export of this case held 374
    # WhatsApp voice messages (.opus); the format was unsupported, every one of
    # them was skipped without a word, and the lawyer had no way to know the
    # majority of the evidence never entered the system.
    result: dict = {
        "scanned": 0, "registered": 0, "duplicates": 0,
        "skipped_unsupported": 0, "skipped_by_type": {}, "errors": [],
    }
    registered_ids: list[int] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            result["skipped_unsupported"] += 1
            key = suffix or "(no extension)"
            result["skipped_by_type"][key] = result["skipped_by_type"].get(key, 0) + 1
            continue
        result["scanned"] += 1
        try:
            ev = register_evidence(session, str(path), case_id=req.case_id)
            registered_ids.append(ev.id)
            result["registered"] += 1
        except DuplicateEvidenceError:
            result["duplicates"] += 1
        except Exception as exc:
            result["errors"].append({"path": str(path), "error": str(exc)})

    if registered_ids:
        background.add_task(_index_in_background)
    return result


@router.delete("/{evidence_id}")
def delete_evidence(evidence_id: int, session: Session = Depends(get_session)):
    ev = session.get(Evidence, evidence_id)
    if not ev:
        raise HTTPException(status_code=404, detail="evidence not found")

    filename = ev.filename
    delete_evidence_record(session, ev)
    log_event(session, "evidence_deleted", evidence_id=evidence_id, filename=filename)
    return {"deleted": evidence_id}


@router.post("/{evidence_id}/reindex")
def reindex_evidence(
    evidence_id: int,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    ev = session.get(Evidence, evidence_id)
    if not ev:
        raise HTTPException(status_code=404, detail="evidence not found")
    ev.status = "processing"
    session.add(ev)
    session.commit()
    background.add_task(_index_in_background)
    return {"id": evidence_id, "status": "processing"}


@router.get("/{evidence_id}/content")
def get_evidence_content(
    evidence_id: int,
    session: Session = Depends(get_session),
):
    ev = session.get(Evidence, evidence_id)

    if not ev:
        raise HTTPException(status_code=404, detail="evidence not found")

    if not ev.mime_type or not ev.mime_type.startswith("text/"):
        raise HTTPException(
            status_code=400,
            detail="preview not supported for this file type",
        )

    path = Path(ev.stored_path)

    if not path.exists():
        raise HTTPException(status_code=404, detail="stored file not found")

    return {
        "id": ev.id,
        "filename": ev.filename,
        "mime_type": ev.mime_type,
        "text": path.read_text(encoding="utf-8", errors="replace"),
        # precomputed by the background worker — instant, no waiting on the LLM
        "translation": ev.translation or "",
        "translation_status": ev.translation_status or "",
    }
