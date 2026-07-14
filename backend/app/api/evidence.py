from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_engine, get_session
from app.models.evidence import Evidence
from app.services.audit_service import log_event
from app.services.evidence_service import (
    SUPPORTED_EXTENSIONS,
    DuplicateEvidenceError,
    ImportPathNotAllowedError,
    delete_evidence_record,
    index_evidence,
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
        "stored_path": ev.stored_path,
        "filename": ev.filename,
        "sha256": ev.sha256,
        "size_bytes": ev.size_bytes,
        "mime_type": ev.mime_type,
        "imported_at": ev.imported_at.isoformat(),
        "status": ev.status,
    }


def _index_in_background(evidence_ids: list[int]) -> None:
    import logging

    # background task: request session is closed by now, open a fresh one
    with Session(get_engine()) as session:
        for evidence_id in evidence_ids:
            try:
                index_evidence(session, evidence_id)
            except Exception:
                logging.getLogger(__name__).exception(
                    "background indexing failed for evidence %s", evidence_id
                )
                ev = session.get(Evidence, evidence_id)
                if ev is not None:
                    ev.status = "text_extraction_failed"
                    session.add(ev)
                    session.commit()


@router.get("")
def list_evidence(
    limit: int = Query(100, ge=1, le=1000),
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

    background.add_task(_index_in_background, [ev.id])
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

    result = {"scanned": 0, "registered": 0, "duplicates": 0, "errors": []}
    registered_ids: list[int] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
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
        background.add_task(_index_in_background, registered_ids)
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
    background.add_task(_index_in_background, [evidence_id])
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
