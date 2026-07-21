from __future__ import annotations

import logging
import os
import re
import threading
import time

from sqlmodel import Session, select

from app.db import get_engine
from app.models.evidence import Evidence, EvidenceChunk
from app.services import background_control, llm_service

logger = logging.getLogger("app.translate_worker")

CYRILLIC_RE = re.compile("[Ѐ-ӿ]")
# a page of Cyrillic is enough to call a document foreign; a stray Russian word
# in a Hebrew file is not worth an hour of GPU time
MIN_CYRILLIC_CHARS = 40
IDLE_SLEEP_SECONDS = float(os.getenv("CASEMIND_TRANSLATE_IDLE_SLEEP", "60"))


def _enabled() -> bool:
    # read at start(), not at import: tests (and any caller that configures the
    # environment after import) must be able to switch the worker off
    return os.getenv("CASEMIND_BACKGROUND_TRANSLATE", "1") != "0"

_started = False
_lock = threading.Lock()


def _evidence_text(session: Session, evidence_id: int) -> str:
    chunks = session.exec(
        select(EvidenceChunk)
        .where(EvidenceChunk.evidence_id == evidence_id)
        .order_by(EvidenceChunk.chunk_index)
    ).all()
    return "\n".join(c.text or "" for c in chunks).strip()


def _next_untranslated(session: Session) -> Evidence | None:
    """Next document to work on: one already part-way through (finish it before
    starting anything new), else the oldest never looked at."""
    return session.exec(
        select(Evidence)
        .where(Evidence.translation_status.in_(("", "pending")))
        .where(Evidence.status.not_in(("processing", "imported")))
        .order_by(Evidence.translation_status.desc(), Evidence.id)  # "pending" first
        .limit(1)
    ).first()


def translate_one(session: Session, evidence: Evidence) -> str:
    """Translate one document to Hebrew and store it. Returns the new status.

    Progress is committed after every chunk. A 83k-char chat takes far longer
    than the gap between restarts, so translating it in one shot meant it was
    started from scratch every time and never finished. Now a restart resumes
    where it stopped.

    Between chunks the worker waits for any user-facing LLM call to finish:
    Ollama serves one request at a time, and a user's question must not sit
    behind hours of background work.
    """
    text = _evidence_text(session, evidence.id)
    cyrillic = len(CYRILLIC_RE.findall(text))
    if cyrillic < MIN_CYRILLIC_CHARS:
        evidence.translation_status = "not_needed"
        session.add(evidence)
        session.commit()
        return evidence.translation_status

    chunks = llm_service.split_for_translation(text)
    done = evidence.translation_chunks_done or 0
    if done > len(chunks):
        # the evidence was re-indexed since we started and the chunking changed;
        # a partial translation of the OLD text must not be stitched to the new
        done = 0
    if done == 0:
        evidence.translation = ""
    logger.info(
        "translating %s (%s chars, %s chunks, resuming at %s)",
        evidence.filename, len(text), len(chunks), done,
    )
    started = time.monotonic()

    for index in range(done, len(chunks)):
        llm_service.wait_until_user_idle()  # the user always goes first
        piece = llm_service.translate_chunk(chunks[index])
        if piece is None:
            # LLM down / failed: keep the progress made, retry the rest later
            session.add(evidence)
            session.commit()
            return "failed"

        evidence.translation = (evidence.translation or "") + ("\n" if index else "") + piece
        evidence.translation_chunks_done = index + 1
        evidence.translation_status = "pending"
        session.add(evidence)
        session.commit()  # survive a restart

    evidence.translation_status = "done"
    session.add(evidence)
    session.commit()
    logger.info("translated %s in %.0fs", evidence.filename, time.monotonic() - started)
    return "done"


def run_forever() -> None:
    """Prepare the material ahead of the user: keep translating foreign
    evidence for as long as the backend runs, so an hour-long translation is
    already done by the time the file is opened. Sequential by design — the
    local model is the bottleneck and running two at once helps nobody."""
    llm_service.mark_background()  # this thread's LLM calls yield to the user
    while True:
        try:
            background_control.wait_while_paused()  # user turned background work off
            with Session(get_engine()) as session:
                # Transcription (Whisper) and translation (Ollama) both want the
                # GPU, and on a small card they do not fit together — the LLM
                # call just times out. Let indexing/transcription finish first;
                # you cannot translate what is not indexed anyway.
                still_indexing = session.exec(
                    select(Evidence.id).where(Evidence.status == "processing").limit(1)
                ).first()
                if still_indexing is not None:
                    time.sleep(IDLE_SLEEP_SECONDS)
                    continue
                evidence = _next_untranslated(session)
                if evidence is None:
                    time.sleep(IDLE_SLEEP_SECONDS)  # backlog clear; check again later
                    continue
                if not llm_service.ollama_available():
                    time.sleep(IDLE_SLEEP_SECONDS)  # no model right now; retry later
                    continue
                translate_one(session, evidence)
        except Exception:
            logger.exception("background translation cycle failed; continuing")
            time.sleep(IDLE_SLEEP_SECONDS)


def start() -> None:
    """Start the worker once per process."""
    global _started
    if not _enabled():
        logger.info("background translation disabled (CASEMIND_BACKGROUND_TRANSLATE=0)")
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=run_forever, daemon=True, name="translate-worker").start()
