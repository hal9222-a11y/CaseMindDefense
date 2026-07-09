from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Evidence(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    original_path: str
    stored_path: str
    filename: str
    sha256: str = Field(index=True, unique=True)
    size_bytes: int = 0
    mime_type: str = "application/octet-stream"
    imported_at: datetime = Field(default_factory=utcnow)
    status: str = "imported"


class EvidenceChunk(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    evidence_id: int = Field(index=True)
    chunk_index: int = 0
    text: str
    source_location: str = ""
    embedding: str = ""


class AuditEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str = Field(index=True)
    evidence_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    details_json: str = "{}"
