import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.services import llm_service
from app.services.entity_service import IDENTIFIER_LABELS, entity_graph, list_entities

router = APIRouter(prefix="/entities", tags=["entities"])

CYRILLIC_RE = re.compile("[Ѐ-ӿ]")
MAX_NAMES_PER_CALL = 40  # each name is one LLM round-trip; keep the wait bounded


class HebrewNamesRequest(BaseModel):
    names: list[str]

@router.get("")
def entities(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    case_id: int | None = Query(None),
    session: Session = Depends(get_session),
):
    return list_entities(session, case_id=case_id)[offset : offset + limit]

@router.post("/hebrew-names")
def hebrew_names(req: HebrewNamesRequest):
    """Hebrew reading for Cyrillic names shown in the Entities list
    (Марина → מרינה), so a Russian case is readable at a glance.
    Returns {russian_name: hebrew_name}; names it cannot render are omitted."""
    if not llm_service.ollama_available():
        raise HTTPException(
            status_code=503,
            detail="תרגום שמות דורש מודל שפה מקומי (Ollama) — לא זמין כרגע",
        )
    targets = [n for n in dict.fromkeys(req.names) if CYRILLIC_RE.search(n or "")]
    if len(targets) > MAX_NAMES_PER_CALL:
        raise HTTPException(
            status_code=413,
            detail=f"יותר מדי שמות בבת אחת ({len(targets)}, מקסימום {MAX_NAMES_PER_CALL}).",
        )
    out: dict[str, str] = {}
    for name in targets:
        hebrew = llm_service.to_hebrew_name(name)
        if hebrew:
            out[name] = hebrew
    return {"names": out, "model": llm_service.active_model()}


@router.get("/graph")
def graph(
    max_nodes: int = Query(30, ge=2, le=100),
    case_id: int | None = Query(None),
    only_people: bool = Query(
        True, description="hide phones/IDs/plates (people, places and orgs stay)"
    ),
    min_count: int = Query(1, ge=1, description="minimum mentions for a node"),
    min_edge_weight: int = Query(
        2, ge=1, description="edge only if the pair shares this many passages"
    ),
    max_edges_per_node: int = Query(
        3, ge=1, le=10, description="keep only each entity's strongest links"
    ),
    session: Session = Depends(get_session),
):
    """Co-occurrence graph. Defaults are tuned to be readable: names only, links
    measured per passage (not per file — one chat contains everyone), and only
    each entity's strongest links kept, otherwise the graph is a hairball."""
    return entity_graph(
        session,
        max_nodes=max_nodes,
        case_id=case_id,
        exclude_types=IDENTIFIER_LABELS if only_people else None,
        min_count=min_count,
        min_edge_weight=min_edge_weight,
        max_edges_per_node=max_edges_per_node,
    )
