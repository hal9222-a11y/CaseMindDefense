from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db import init_db
from app.api import health, evidence, search, audit, entities, timeline, contradictions, ai, cases

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="CaseMind Defense API", version="0.10-alpha", lifespan=lifespan)

app.include_router(health.router)
app.include_router(evidence.router)
app.include_router(search.router)
app.include_router(audit.router)
app.include_router(entities.router)
app.include_router(timeline.router)
app.include_router(contradictions.router)
app.include_router(ai.router)
app.include_router(cases.router)
