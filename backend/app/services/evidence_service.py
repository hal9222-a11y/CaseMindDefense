import logging
import mimetypes
import os
import shutil
import threading
from pathlib import Path
from sqlalchemy import func
from sqlmodel import Session, select
from app.core.settings import get_settings
from app.models.evidence import Evidence, EvidenceChunk, ExtractedEntity
from app.services.audit_service import log_event
from app.services.chat_service import chunk_by_messages, is_chat_export
from app.services.embedding_service import embed_text, embedding_model_name, serialize_embedding
from app.services.hash_service import sha256_file
from app.services import llm_service, search_index
from app.services.ner_service import extract_entities
from app.services.transcription_service import MEDIA_EXTENSIONS, transcribe_to_chunks
from app.services.text_service import (
    IMAGE_EXTENSIONS,
    TextExtractionError,
    chunk_text_with_offsets,
    extract_text,
)

logger = logging.getLogger(__name__)


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
    # our own store is always a legitimate source — the UFDR media extractor
    # stages files there before registering them
    if path.is_relative_to(get_settings().evidence_store_dir):
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
    ".xml",  # forensic export manifests / call logs — data lives in attributes
    ".csv",  # call logs / cell records ship as CSV in forensic exports
    ".html", ".htm",  # saved pages / report exports — indexed as tag-stripped text
    ".ufdr",  # Cellebrite phone-extraction report (zip): chats + contacts inside
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
        # copy via temp + atomic rename: a copy that dies midway (disk full,
        # unplugged drive) must not leave a truncated file at the final name —
        # the next import attempt would see it "exists", skip the copy, and
        # register evidence pointing at a corrupt copy of the original
        tmp = stored.with_suffix(stored.suffix + ".part")
        try:
            shutil.copy2(src, tmp)
            tmp.replace(stored)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

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


def _ufdr_chunks(stored: Path) -> list[dict]:
    """Every conversation in a Cellebrite report as message chunks, plus a
    contacts-directory chunk so the phone book (name <-> number) is searchable
    and its names are extracted as people. Each chunk's speakers (name + phone)
    flow through the same entity/graph pipeline as a WhatsApp export."""
    from app.services.ufdr_service import extract_ufdr

    data = extract_ufdr(stored)
    chunks: list[dict] = []
    for chat in data["chats"]:
        chunks.extend(chat["chunks"])
    if data["contacts"]:
        directory = "\n".join(f"{name}: +{num}" for num, name in data["contacts"].items())
        chunks.append({
            "text": "אנשי קשר (מדריך המכשיר):\n" + directory,
            "source_location": "contacts",
            "speakers": list(data["contacts"].values()),
        })
    return chunks


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

    if stored.suffix.lower() == ".ufdr":
        chunks = _ufdr_chunks(stored)
        extraction_method = "ufdr"
    elif stored.suffix.lower() in MEDIA_EXTENSIONS:
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

    # A photo with NO readable text used to land in 'no_text_found' and vanish
    # from search. When OCR finds nothing in an image, ask a vision model to
    # describe it so it's still findable ("locate the picture of the car"). Only
    # the text-less images pay the vision cost; an image whose OCR already gave
    # text keeps that. Best-effort — disabled/failed captioning leaves the image
    # exactly as OCR left it. Cross-lingual embeddings make the description
    # findable in Hebrew even if the model answers in English.
    if not chunks and stored.suffix.lower() in IMAGE_EXTENSIONS:
        caption = llm_service.describe_image(stored)
        if caption:
            extraction_method = "caption"  # no OCR text — the description IS the content
            chunks = [{"text": caption, "source_location": "image:description"}]

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

        # A caption is a vision model's guess, not case content. Running NER on
        # it would inject invented "people"/places (the model hallucinates names)
        # into the entity graph as if they were real parties. Keep the caption
        # searchable (embedded above) but never let it create entities.
        found = [] if extraction_method == "caption" else extract_entities(chunk_text)

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
    # the chunk set just changed — drop the semantic-search matrix cache so the
    # next query rebuilds (a reindex can reuse rowids and fool its signature)
    search_index.invalidate()
    log_event(session, "evidence_indexed", evidence_id=evidence.id, chunks=len(chunks))

    # standing queries: flag key names/phones in this fresh material.
    # best-effort — a watchlist bug must never fail the indexing itself.
    try:
        from app.services.watchlist_service import scan_evidence

        scan_evidence(session, evidence.id)
    except Exception:
        logger.exception("watchlist scan failed for evidence %s", evidence.id)
        session.rollback()

    return evidence


def import_file(session: Session, source_path: str, case_id: int | None = None) -> Evidence:
    """Synchronous register + index (used by folder import and tests;
    the API endpoint runs index_evidence as a background task instead)."""
    evidence = register_evidence(session, source_path, case_id=case_id)
    return index_evidence(session, evidence.id)


# one resume loop per process: it is started from three places (startup thread,
# /admin/reindex-all, /admin/reindex-pending) and the models are process-global
# and not safe under concurrent inference
_RESUME_LOCK = threading.Lock()


def _processing_priority():
    """SQL ordering that works the FAST, high-value material off the queue
    first: text/chats/UFDR (instant) → images (OCR) → audio (minutes) → video
    (hours). A phone case has hundreds of hours of recordings; without this the
    queue is id-order and a lawyer waits days for the WhatsApp chats to appear
    behind a wall of interrogation video."""
    from sqlalchemy import case

    from app.services.text_service import IMAGE_EXTENSIONS
    from app.services.transcription_service import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS

    fname = func.lower(Evidence.filename)
    tier = case(
        (_suffix_in(fname, VIDEO_EXTENSIONS), 4),
        (_suffix_in(fname, AUDIO_EXTENSIONS), 3),
        (_suffix_in(fname, IMAGE_EXTENSIONS), 2),
        else_=1,  # text, chat, xml, csv, ufdr, pdf, office docs
    )
    return tier, Evidence.id


def _suffix_in(fname_col, extensions):
    from sqlalchemy import or_

    return or_(*[fname_col.like(f"%{ext}") for ext in extensions])


def resume_pending_indexing() -> int:
    """Index every evidence in 'processing' until none remain. Covers both
    items orphaned by a crash/restart and items freshly marked by reindex-all.
    Fetches the next item each iteration (not a snapshot), so work queued while
    the loop runs is picked up instead of waiting for the next restart. If a
    loop is already running, returns immediately — that loop will get to the
    new items. Returns the count processed by THIS call."""
    import logging

    from app.db import get_engine
    from app.services import background_control

    logger = logging.getLogger("app.resume")
    if not _RESUME_LOCK.acquire(blocking=False):
        logger.info("resume already running; the active loop will pick up new items")
        return 0

    import errno
    import shutil
    import time

    from sqlalchemy.exc import OperationalError

    from app.core.settings import get_settings

    _DISK_MIN_FREE = 2**30  # 1 GB: below this a drive is "full" — pause, don't thrash
    # The DB and the evidence store can sit on DIFFERENT drives (e.g. DB on F:,
    # media on D:). A SQLite "disk I/O error" means the DB drive is full; an
    # ENOSPC on a WAV/extract write means the store drive is full. Watch BOTH.
    _settings = get_settings()
    _store_dir = _settings.evidence_store_dir
    _db_dir = Path(_settings.database_url.replace("sqlite:///", "", 1)).parent

    def _min_free_bytes() -> int | None:
        """Least free space across the store and DB drives; None if neither
        can be stat'd (both drives gone — a dropout, not a full disk)."""
        frees = []
        for path in (_store_dir, _db_dir):
            try:
                frees.append(shutil.disk_usage(path).free)
            except OSError:
                pass
        return min(frees) if frees else None

    done = 0
    attempted: set[int] = set()  # never retry an id within one run — no spin on a row that can't be marked failed
    io_failures = 0
    try:
        # The evidence DB lives on a drive that drops out intermittently; a single
        # disk I/O error here used to kill this loop silently and the whole queue
        # (tens of thousands of items) sat idle until the next restart. On
        # OperationalError: reconnect and resume; give up only if the drive stays
        # gone for 20 straight attempts (~5 minutes).
        while True:
            try:
                with Session(get_engine()) as session:
                    while True:
                        background_control.wait_while_paused()  # user paused background work
                        query = select(Evidence.id).where(Evidence.status == "processing")
                        if attempted:
                            query = query.where(Evidence.id.not_in(attempted))
                        # fast/high-value types first, oldest within a tier
                        evidence_id = session.exec(
                            query.order_by(*_processing_priority()).limit(1)
                        ).first()
                        if evidence_id is None:
                            break
                        attempted.add(evidence_id)
                        try:
                            index_evidence(session, evidence_id)
                            done += 1
                            io_failures = 0
                        except OperationalError:
                            # a drive dropout, not a bad row — retry it after reconnect
                            attempted.discard(evidence_id)
                            raise
                        except Exception as exc:
                            # A full disk is not a bad file: don't mark it failed
                            # (the row would need reprocessing once space frees).
                            # Bubble it up so the outer handler pauses.
                            if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
                                attempted.discard(evidence_id)
                                raise
                            logger.exception("resume-index failed for evidence %s", evidence_id)
                            session.rollback()
                            ev = session.get(Evidence, evidence_id)
                            if ev is not None:
                                ev.status = "text_extraction_failed"
                                session.add(ev)
                                session.commit()
                break  # queue drained
            except (OperationalError, OSError) as exc:
                if isinstance(exc, OSError) and exc.errno != errno.ENOSPC:
                    raise  # an unrelated OS error — don't swallow it
                # Disk problem. A full drive still answers disk_usage; a vanished
                # one raises. Full → retrying can't help until the user frees
                # space, so pause here (thread stays alive, no watchdog restart-
                # thrash) and auto-resume when space returns. Dropout → the
                # existing reconnect-and-eventually-give-up path.
                free = _min_free_bytes()
                if free is not None and free < _DISK_MIN_FREE:
                    logger.error("resume: disk full (%.1f GB free); pausing until space is freed",
                                 free / 2**30)
                    while True:
                        time.sleep(30)
                        recovered = _min_free_bytes()
                        if recovered is None or recovered >= _DISK_MIN_FREE:
                            break  # space back, or both drives vanished (dropout path)
                    io_failures = 0
                    logger.info("resume: disk space recovered; resuming indexing")
                    continue
                io_failures += 1
                if io_failures > 20:
                    logger.error("resume: giving up after %d consecutive disk I/O failures", io_failures)
                    raise
                logger.warning("resume: disk I/O error (%d), reconnecting in 15s", io_failures)
                time.sleep(15)
    finally:
        _RESUME_LOCK.release()
    if attempted:
        logger.warning("resume complete: %d/%d indexed", done, len(attempted))
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
    search_index.invalidate()  # chunks removed — force the search matrix to rebuild

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
