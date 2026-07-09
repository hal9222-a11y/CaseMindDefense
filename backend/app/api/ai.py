from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session
from app.db import get_session
from app.services.evidence_ai_service import answer_with_evidence

router = APIRouter(prefix="/ai", tags=["ai"])

class AskRequest(BaseModel):
    question: str

@router.post("/ask")
def ask(req: AskRequest, session: Session = Depends(get_session)):
    return answer_with_evidence(session=session, question=req.question, limit=5)
