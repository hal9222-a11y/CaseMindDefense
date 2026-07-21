from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import llm_service

router = APIRouter(tags=["translate"])


# Measured on a local 8B model against real chat text: ~10 chars/sec. A whole
# forensic export (70k+ chars) would therefore take hours, which is not a
# blocking HTTP request. Cap at what finishes in a tolerable wait and tell the
# user to translate a selection instead — that is the realistic workflow anyway.
MAX_TRANSLATE_CHARS = 20_000


class TranslateRequest(BaseModel):
    text: str
    target: str = "Hebrew"


@router.post("/translate")
def translate(req: TranslateRequest):
    """Translate free text into the target language (default Hebrew) with the
    local LLM — for reading Russian/other-language evidence. Long documents are
    translated in chunks. 503 when no LLM is available (translation needs one;
    there is no offline fallback)."""
    if not req.text.strip():
        return {"translated": "", "model": None}
    if len(req.text) > MAX_TRANSLATE_CHARS:
        # a raw 422 here just says "string too long" — say what to do instead
        raise HTTPException(
            status_code=413,
            detail=(
                f"המסמך ארוך מדי לתרגום מלא ({len(req.text):,} תווים, "
                f"המקסימום {MAX_TRANSLATE_CHARS:,}). סמן קטע בתצוגה ותרגם רק אותו."
            ),
        )
    result = llm_service.translate(req.text, target=req.target)
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="תרגום דורש מודל שפה מקומי (Ollama) — לא זמין כרגע",
        )
    return {"translated": result, "model": llm_service.active_model()}
