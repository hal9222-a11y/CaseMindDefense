import mimetypes
import shutil
from pathlib import Path
from sqlmodel import Session, select
from app.core.settings import get_settings
from app.models.evidence import Evidence, EvidenceChunk
from app.services.audit_service import log_event
from app.services.embedding_service import embed_text, serialize_embedding
from app.services.hash_service import sha256_file
from app.services.text_service import TextExtractionError, chunk_text_with_offsets, extract_text

class DuplicateEvidenceError(Exception):
    def __init__(self, existing_id: int):
        super().__init__(f"Duplicate evidence: existing id {existing_id}")
        self.existing_id = existing_id

SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp", ".docx", ".xlsx", ".pptx", ".eml", ".msg", ".wav", ".mp3", ".mp4"}

def import_file(session: Session, source_path: str) -> Evidence:
    src = Path(source_path).resolve()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(source_path)

    digest = sha256_file(src)
    existing = session.exec(select(Evidence).where(Evidence.sha256 == digest)).first()
    if existing:
        raise DuplicateEvidenceError(existing.id or -1)

    store_dir = get_settings().evidence_store_dir
    store_dir.mkdir(parents=True, exist_ok=True)
    stored = store_dir / f"{digest}{src.suffix.lower()}"
    if not stored.exists():
        shutil.copy2(src, stored)

    evidence = Evidence(
        original_path=str(src),
        stored_path=str(stored),
        filename=src.name,
        sha256=digest,
        size_bytes=src.stat().st_size,
        mime_type=mimetypes.guess_type(src.name)[0] or "application/octet-stream",
        status="imported",
    )
    session.add(evidence)
    session.commit()
    session.refresh(evidence)

    log_event(session, "evidence_imported", evidence_id=evidence.id, original_path=str(src), stored_path=str(stored), sha256=digest)

    try:
        text = extract_text(src)
    except TextExtractionError as exc:
        evidence.status = "text_extraction_failed"
        session.add(evidence)
        session.commit()
        session.refresh(evidence)
        log_event(session, "text_extraction_failed", evidence_id=evidence.id, error=str(exc), source_path=str(src))
        return evidence

    chunks = chunk_text_with_offsets(text)
    for idx, chunk_data in enumerate(chunks):
        chunk_text = (chunk_data.get("text") or "").strip()
        if not chunk_text:
            continue
        ev_chunk = EvidenceChunk(
            evidence_id=evidence.id,
            chunk_index=idx,
            text=chunk_text,
            source_location=chunk_data.get("source_location") or f"chunk:{idx}",
            embedding=serialize_embedding(embed_text(chunk_text)),
        )
        session.add(ev_chunk)

    evidence.status = "indexed" if chunks else "no_text_found"
    session.add(evidence)
    session.commit()
    session.refresh(evidence)
    log_event(session, "evidence_indexed", evidence_id=evidence.id, chunks=len(chunks))
    return evidence

def import_folder(session: Session, folder_path: str) -> dict:
    root = Path(folder_path).resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(folder_path)
    result = {"scanned": 0, "imported": 0, "duplicates": 0, "errors": []}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        result["scanned"] += 1
        try:
            import_file(session, str(path))
            result["imported"] += 1
        except DuplicateEvidenceError:
            result["duplicates"] += 1
        except Exception as exc:
            result["errors"].append({"path": str(path), "error": str(exc)})
    return result
