from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.models.evidence import Evidence
from app.services import background_control, llm_service
from app.services.evidence_service import MEDIA_EXTENSIONS
from app.services.text_service import IMAGE_EXTENSIONS

router = APIRouter(tags=["status"])


def _stage_for(filename: str | None) -> str:
    """Infer the background stage a file is in from its type (indexing is
    sequential, so the oldest 'processing' item is the one being worked on)."""
    suffix = Path(filename or "").suffix.lower()
    if suffix in MEDIA_EXTENSIONS:
        return "תמלול"          # audio/video → speech-to-text
    if suffix in IMAGE_EXTENSIONS or suffix == ".pdf":
        return "OCR"            # scanned image / PDF → OCR
    return "אינדוקס"            # text extraction + embedding


# evidence that carries searchable text; anything else is either still queued,
# genuinely textless (a 16x16 UI icon), or a failure worth surfacing
INDEXED_STATUSES = ("indexed", "ocr_indexed", "transcribed")
EMPTY_STATUSES = ("no_text_found", "extraction_not_supported")


@router.get("/status")
def status(session: Session = Depends(get_session)):
    """A cheap snapshot of what the system is doing right now — for the
    desktop activity indicator. Counts + the current file, no heavy work."""
    total = session.exec(select(func.count()).select_from(Evidence)).one()
    processing = session.exec(
        select(func.count()).select_from(Evidence).where(Evidence.status == "processing")
    ).one()

    # "did it finish the material?" — indexed vs textless vs failed, so the user
    # can tell a completed backlog from a silently broken one
    indexed = session.exec(
        select(func.count()).select_from(Evidence)
        .where(Evidence.status.in_(INDEXED_STATUSES))
    ).one()
    empty = session.exec(
        select(func.count()).select_from(Evidence)
        .where(Evidence.status.in_(EMPTY_STATUSES))
    ).one()
    failed = total - processing - indexed - empty

    # background translation backlog: how much foreign material is still being
    # prepared, so the user can see the machine is working ahead of them
    translated = session.exec(
        select(func.count()).select_from(Evidence)
        .where(Evidence.translation_status == "done")
    ).one()
    to_translate = session.exec(
        select(func.count()).select_from(Evidence)
        .where(Evidence.translation_status.in_(("", "pending")))
        .where(Evidence.status.not_in(("processing", "imported")))
    ).one()

    current = None
    if processing:
        # cheap approximation of "what's being worked on" — oldest processing id.
        # Using the real _processing_priority() order here meant a LIKE-based sort
        # over ~190k rows (~4s) on EVERY 4s poll, which is what made the desktop
        # time out and read the backend as "down". A status hint doesn't need the
        # exact head of the queue; ORDER BY id hits the status index and is instant.
        row = session.exec(
            select(Evidence).where(Evidence.status == "processing")
            .order_by(Evidence.id).limit(1)
        ).first()
        if row is not None:
            current = {"filename": row.filename, "stage": _stage_for(row.filename)}

    return {
        "ok": True,
        "evidence_total": total,
        "processing": processing,
        "busy": processing > 0,
        "current": current,
        "indexed": indexed,
        "no_text": empty,
        "failed": failed,
        "translated": translated,
        "to_translate": to_translate,
        "llm_available": llm_service.ollama_available(),
        "llm_model": llm_service.active_model(),
        "llm_provider": llm_service.LLM_PROVIDER,  # "ollama" (local) or "gemini" (cloud)
        "background_enabled": not background_control.is_paused(),
    }
