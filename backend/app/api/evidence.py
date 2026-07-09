from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models.evidence import Evidence
from app.services.evidence_service import (
    DuplicateEvidenceError,
    import_file,
    import_folder,
)

router = APIRouter(prefix="/evidence", tags=["evidence"])


class ImportFileRequest(BaseModel):
    path: str


class ImportFolderRequest(BaseModel):
    path: str


@router.get("")
def list_evidence(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    return session.exec(
        select(Evidence).order_by(Evidence.id).offset(offset).limit(limit)
    ).all()


@router.post("/import-file")
def import_file_endpoint(
    req: ImportFileRequest,
    session: Session = Depends(get_session),
):
    try:
        ev = import_file(session, req.path)
        return {
            "id": ev.id,
            "original_path": ev.original_path,
            "stored_path": ev.stored_path,
            "filename": ev.filename,
            "sha256": ev.sha256,
            "size_bytes": ev.size_bytes,
            "mime_type": ev.mime_type,
            "imported_at": ev.imported_at.isoformat(),
            "status": ev.status,
        }
    except DuplicateEvidenceError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "duplicate", "existing_id": exc.existing_id},
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="file not found")


@router.post("/import-folder")
def import_folder_endpoint(
    req: ImportFolderRequest,
    session: Session = Depends(get_session),
):
    try:
        return import_folder(session, req.path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="folder not found")


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
    }