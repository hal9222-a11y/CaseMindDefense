from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import llm_service

router = APIRouter(tags=["translate"])


class TranslateRequest(BaseModel):
    text: str = Field(max_length=20000)
    target: str = "Hebrew"


@router.post("/translate")
def translate(req: TranslateRequest):
    """Translate free text into the target language (default Hebrew) with the
    local LLM — for reading Russian/other-language evidence. 503 when no LLM
    is available (translation needs one; there is no offline fallback)."""
    if not req.text.strip():
        return {"translated": "", "model": None}
    result = llm_service.translate(req.text, target=req.target)
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="תרגום דורש מודל שפה מקומי (Ollama) — לא זמין כרגע",
        )
    return {"translated": result, "model": llm_service.active_model()}
