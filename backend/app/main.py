from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from app.core.security import require_api_key
from app.db import init_db
from app.api import health, evidence, search, audit, entities, timeline, contradictions, ai, cases, reports, admin

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="CaseMind Defense API", version="0.15-alpha", lifespan=lifespan)

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
