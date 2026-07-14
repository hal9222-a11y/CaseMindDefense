from __future__ import annotations

import logging
import os
import re
import threading
import time

from sqlmodel import Session, select

from app.db import get_engine
from app.models.evidence import Evidence, EvidenceChunk
from app.services import llm_service

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
    """Oldest indexed evidence that has never been looked at for translation."""
    return session.exec(
        select(Evidence)
        .where(Evidence.translation_status == "")
        .where(Evidence.status.not_in(("processing", "imported")))
        .order_by(Evidence.id)
        .limit(1)
    ).first()


def translate_one(session: Session, evidence: Evidence) -> str:
    """Translate one document to Hebrew and store it. Returns the new status.
    Documents that are not foreign are marked not_needed so we never look
    at them again."""
    text = _evidence_text(session, evidence.id)
    cyrillic = len(CYRILLIC_RE.findall(text))
    if cyrillic < MIN_CYRILLIC_CHARS:
        evidence.translation_status = "not_needed"
    else:
        logger.info(
            "translating %s (%s chars, %s cyrillic)", evidence.filename, len(text), cyrillic
        )
        started = time.monotonic()
        # no size cap here on purpose: this is the slow path the user is not
        # waiting on, and it is chunked internally
        hebrew = llm_service.translate(text)
        if hebrew:
            evidence.translation = hebrew
            evidence.translation_status = "done"
            logger.info(
                "translated %s in %.0fs", evidence.filename, time.monotonic() - started
            )
        else:
            # LLM down or failed — leave it unclaimed so it is retried later
            evidence.translation_status = ""
            return "failed"

    session.add(evidence)
    session.commit()
    return evidence.translation_status


def run_forever() -> None:
    """Prepare the material ahead of the user: keep translating foreign
    evidence for as long as the backend runs, so an hour-long translation is
    already done by the time the file is opened. Sequential by design — the
    local model is the bottleneck and running two at once helps nobody."""
    while True:
        try:
            with Session(get_engine()) as session:
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
