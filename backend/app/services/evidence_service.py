import mimetypes
import os
import shutil
from pathlib import Path
from sqlmodel import Session, select
from app.core.settings import get_settings
from app.models.evidence import Evidence, EvidenceChunk, ExtractedEntity
from app.services.audit_service import log_event
from app.services.chat_service import chunk_by_messages, is_chat_export
from app.services.embedding_service import embed_text, embedding_model_name, serialize_embedding
from app.services.hash_service import sha256_file
from app.services.ner_service import extract_entities
from app.services.transcription_service import MEDIA_EXTENSIONS, transcribe_to_chunks
from app.services.text_service import TextExtractionError, chunk_text_with_offsets, extract_text

class DuplicateEvidenceError(Exception):
    def __init__(self, existing_id: int):
        super().__init__(f"Duplicate evidence: existing id {existing_id}")
        self.existing_id = existing_id


class ImportPathNotAllowedError(Exception):
    pass


def _check_import_allowed(path: Path) -> None:
    """When CASEMIND_IMPORT_ROOTS is set (os.pathsep-separated directories),
    imports are restricted to those trees — blocks the API from being used
    to read arbitrary system files. Unset = open local mode."""
    roots = os.getenv("CASEMIND_IMPORT_ROOTS")
    if not roots:
        return
    for root in roots.split(os.pathsep):
        root = root.strip()
        if root and path.is_relative_to(Path(root).resolve()):
            return
    raise ImportPathNotAllowedError(f"import path outside allowed roots: {path}")

SUPPORTED_EXTENSIONS = {
    ".txt", ".pdf",
    ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp",
    ".docx", ".xlsx", ".pptx", ".eml", ".msg",
    *MEDIA_EXTENSIONS,
}

def register_evidence(session: Session, source_path: str, case_id: int | None = None) -> Evidence:
    """Fast synchronous part of import: hash, dedupe, copy into the store,
    insert with status=processing. Text extraction happens in index_evidence."""
    src = Path(source_path).resolve()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(source_path)
    _check_import_allowed(src)

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
        case_id=case_id,
        original_path=str(src),
        stored_path=str(stored),
        filename=src.name,
        sha256=digest,
        size_bytes=src.stat().st_size,
        mime_type=mimetypes.guess_type(src.name)[0] or "application/octet-stream",
        status="processing",
    )
    session.add(evidence)
    session.commit()
    session.refresh(evidence)

    log_event(session, "evidence_imported", evidence_id=evidence.id, original_path=str(src), stored_path=str(stored), sha256=digest, case_id=case_id)
    return evidence


def _drop_old_index(session: Session, evidence_id: int) -> None:
    for old_chunk in session.exec(
        select(EvidenceChunk).where(EvidenceChunk.evidence_id == evidence_id)
    ).all():
        session.delete(old_chunk)
    for old_entity in session.exec(
        select(ExtractedEntity).where(ExtractedEntity.evidence_id == evidence_id)
    ).all():
        session.delete(old_entity)


def index_evidence(session: Session, evidence_id: int) -> Evidence:
    """Extract text, chunk, embed. Replaces any existing chunks (reindex-safe).

    The old index is dropped only once the new one is ready, in the same
    transaction. Deleting it up-front left the evidence with ZERO chunks for as
    long as OCR or transcription took — minutes — during which it was invisible
    to search, the timeline and the AI. A lawyer searching in that window would
    be told the material is not in the case, which is the same lie as a search
    that invents evidence, pointing the other way.
    """
    evidence = session.get(Evidence, evidence_id)
    if evidence is None:
        raise ValueError(f"evidence {evidence_id} not found")

    stored = Path(evidence.stored_path)

    if stored.suffix.lower() in MEDIA_EXTENSIONS:
        media_chunks = transcribe_to_chunks(stored)
        if media_chunks is None:
            evidence.status = "transcription_unavailable"
            session.add(evidence)
            session.commit()
            session.refresh(evidence)
            log_event(session, "transcription_unavailable", evidence_id=evidence.id)
            return evidence
        chunks = media_chunks
        extraction_method = "transcription"
    else:
        try:
            text, extraction_method = extract_text(stored)
        except TextExtractionError as exc:
            evidence.status = "text_extraction_failed"
            session.add(evidence)
            session.commit()
            session.refresh(evidence)
            log_event(session, "text_extraction_failed", evidence_id=evidence.id, error=str(exc))
            return evidence
        # A WhatsApp export is a conversation, not a wall of text. Chunking it
        # on message boundaries keeps citations whole, and — far more important
        # — lets us record WHO SPOKE in each passage. The participants are the
        # people the case is actually about, and they were never extracted.
        if is_chat_export(text):
            chunks = chunk_by_messages(text)
            extraction_method = "chat"
        else:
            chunks = chunk_text_with_offsets(text)

    # Build the whole new index in memory FIRST. Embedding and NER are the slow
    # part, and the evidence must stay searchable while they run.
    new_chunks: list[EvidenceChunk] = []
    new_entities: list[ExtractedEntity] = []

    for idx, chunk_data in enumerate(chunks):
        chunk_text = chunk_data.get("text") or ""
        if not chunk_text.strip():
            continue
        vec = embed_text(chunk_text)
        new_chunks.append(
            EvidenceChunk(
                evidence_id=evidence.id,
                chunk_index=idx,
                text=chunk_text,
                source_location=chunk_data.get("source_location") or f"chunk:{idx}",
                embedding=serialize_embedding(vec),
                embedding_model=embedding_model_name(),
                embedding_dimension=len(vec),
            )
        )

        found = extract_entities(chunk_text)

        # The people who sent the messages in this passage. Recording them makes
        # the conversation participants first-class people, and because both
        # sides of a chat appear in the same passage, the graph then shows who
        # actually talks to whom.
        for speaker in chunk_data.get("speakers", []):
            found.append({"text": speaker, "label": "person"})

        seen: set[tuple[str, str]] = set()
        for entity in found:
            key = (entity["text"], entity["label"])
            if key in seen:
                continue
            seen.add(key)
            new_entities.append(
                ExtractedEntity(
                    evidence_id=evidence.id,
                    chunk_index=idx,
                    text=entity["text"],
                    label=entity["label"],
                )
            )

    # Swap old for new in one transaction: the evidence is never chunk-less, so
    # a search running right now cannot be told the material is not in the case.
    _drop_old_index(session, evidence_id)
    for chunk in new_chunks:
        session.add(chunk)
    for entity in new_entities:
        session.add(entity)

    if chunks:
        evidence.status = {
            "ocr": "ocr_indexed",
            "transcription": "transcribed",
        }.get(extraction_method, "indexed")
    elif extraction_method == "unsupported":
        evidence.status = "extraction_not_supported"
    else:
        evidence.status = "no_text_found"
    session.add(evidence)
    session.commit()
    session.refresh(evidence)
    log_event(session, "evidence_indexed", evidence_id=evidence.id, chunks=len(chunks))
    return evidence


def import_file(session: Session, source_path: str, case_id: int | None = None) -> Evidence:
    """Synchronous register + index (used by folder import and tests;
    the API endpoint runs index_evidence as a background task instead)."""
    evidence = register_evidence(session, source_path, case_id=case_id)
    return index_evidence(session, evidence.id)


def resume_pending_indexing() -> int:
    """Re-index every evidence stuck in 'processing'. Background indexing runs
    as one task per folder-import; if the process restarts or the task dies
    mid-batch, those items are orphaned forever. Called on startup (in a
    thread) and by the admin endpoint. Runs sequentially — the models are
    process-global and not safe under concurrent inference. Returns the count
    processed."""
    import logging

    from app.db import get_engine

    logger = logging.getLogger("app.resume")
    with Session(get_engine()) as session:
        pending = list(session.exec(select(Evidence.id).where(Evidence.status == "processing")).all())
    if not pending:
        return 0
    logger.warning("resuming %d evidence stuck in 'processing'", len(pending))

    done = 0
    with Session(get_engine()) as session:
        for evidence_id in pending:
            try:
                index_evidence(session, evidence_id)
                done += 1
            except Exception:
                logger.exception("resume-index failed for evidence %s", evidence_id)
                ev = session.get(Evidence, evidence_id)
                if ev is not None:
                    ev.status = "text_extraction_failed"
                    session.add(ev)
                    session.commit()
    logger.warning("resume complete: %d/%d indexed", done, len(pending))
    return done


def delete_evidence_record(session: Session, evidence: Evidence) -> None:
    """Remove an evidence row and everything derived from it: chunks (via the
    ORM so the FTS delete triggers fire), extracted entities, and the stored
    file. Caller commits and audits. Shared by single-item delete and full
    case delete."""
    from sqlmodel import delete as sql_delete

    for chunk in session.exec(
        select(EvidenceChunk).where(EvidenceChunk.evidence_id == evidence.id)
    ).all():
        session.delete(chunk)
    session.exec(sql_delete(ExtractedEntity).where(ExtractedEntity.evidence_id == evidence.id))

    stored = Path(evidence.stored_path)
    session.delete(evidence)
    session.commit()

    if stored.exists():
        try:
            stored.unlink()
        except OSError:
            pass  # file locked/gone; the DB record is already removed


def import_folder(session: Session, folder_path: str, case_id: int | None = None) -> dict:
    root = Path(folder_path).resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(folder_path)
    result = {"scanned": 0, "imported": 0, "duplicates": 0, "errors": []}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        result["scanned"] += 1
        try:
            import_file(session, str(path), case_id=case_id)
            result["imported"] += 1
        except DuplicateEvidenceError:
            result["duplicates"] += 1
        except Exception as exc:
            result["errors"].append({"path": str(path), "error": str(exc)})
    return result
