import os

# Local-first: load ML models (embeddings, Whisper, NER) straight from the HF
# cache and never phone home. Without this, every model load fires ~30 HuggingFace
# HTTP calls to revalidate the cache — network-bound, breaks offline use, and
# made the first search/AI request blow the desktop's 15s read timeout. Must run
# before any huggingface_hub/transformers import (they freeze these at import).
# ponytail: setdefault so a machine that still needs to download a model can
# override with HF_HUB_OFFLINE=0.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.security import require_api_key
from app.core.settings import get_settings
from app.db import init_db
from app.api import health, evidence, search, audit, entities, timeline, contradictions, ai, cases, reports, admin, persons, status, translate


def _setup_file_logging() -> None:
    logs_dir = get_settings().evidence_store_dir.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    handler = RotatingFileHandler(
        logs_dir / "backend.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_file_logging()
    init_db()
    logging.getLogger(__name__).info("CaseMind backend started")
    # off the main thread so startup (and /health) is not blocked. Two
    # independent daemons — kept separate so the slow warm-up can't delay the
    # resume (that ordering matters for deterministic tests):
    #  1. warm the embedding model (~10s cold import) so the user's first
    #     semantic search / AI query costs ~50ms instead of racing the 15s
    #     client timeout
    #  2. resume any evidence orphaned in 'processing' by a prior crash/restart
    import threading

    from app.services.embedding_service import embed_text
    from app.services.evidence_service import resume_pending_indexing

    threading.Thread(target=lambda: embed_text("warmup", kind="query"), daemon=True).start()
    threading.Thread(target=resume_pending_indexing, daemon=True).start()
    yield

app = FastAPI(title="CaseMind Defense API", version="0.15-alpha", lifespan=lifespan)


@app.exception_handler(Exception)
async def _log_unhandled(request: Request, exc: Exception) -> JSONResponse:
    # request-level 500s otherwise vanish into uvicorn's stderr (a hidden
    # window in the packaged app); log the full traceback to backend.log so
    # every server error is diagnosable from the file the user can send
    logging.getLogger("app.request").exception(
        "unhandled error on %s %s", request.method, request.url.path
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


# /health stays open (liveness probe); everything else requires the API key
# whenever CASEMIND_API_KEY is set
app.include_router(health.router)
protected = [Depends(require_api_key)]
app.include_router(evidence.router, dependencies=protected)
app.include_router(search.router, dependencies=protected)
app.include_router(audit.router, dependencies=protected)
app.include_router(entities.router, dependencies=protected)
app.include_router(timeline.router, dependencies=protected)
app.include_router(contradictions.router, dependencies=protected)
app.include_router(ai.router, dependencies=protected)
app.include_router(cases.router, dependencies=protected)
app.include_router(reports.router, dependencies=protected)
app.include_router(admin.router, dependencies=protected)
app.include_router(persons.router, dependencies=protected)
app.include_router(status.router, dependencies=protected)
app.include_router(translate.router, dependencies=protected)
