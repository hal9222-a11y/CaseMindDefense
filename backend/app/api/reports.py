from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.services.audit_service import log_event
from app.services.report_service import generate_report

router = APIRouter(prefix="/reports", tags=["reports"])


class GenerateReportRequest(BaseModel):
    case_id: int | None = None


@router.post("")
def create_report(req: GenerateReportRequest, session: Session = Depends(get_session)):
    result = generate_report(session, case_id=req.case_id)
    log_event(session, "report_generated", case_id=req.case_id, path=result["path"])
    return result
