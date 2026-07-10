from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Case(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Evidence(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: Optional[int] = Field(default=None, foreign_key="case.id", index=True)
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
    evidence_id: int = Field(foreign_key="evidence.id", index=True)
    chunk_index: int = 0
    text: str
    source_location: str = ""
    embedding: str = ""
    embedding_model: str = ""
    embedding_dimension: int = 0
    embedding_version: str = "1"


class ExtractedEntity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    evidence_id: int = Field(foreign_key="evidence.id", index=True)
    chunk_index: int = 0
    text: str = Field(index=True)
    label: str = Field(index=True)


class AuditEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str = Field(index=True)
    evidence_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    details_json: str = "{}"
    # tamper-evident hash chain: event_hash covers this event + prev_hash,
    # so modifying or removing any past event breaks every hash after it
    prev_hash: str = ""
    event_hash: str = ""
