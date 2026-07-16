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
    # Hebrew translation, precomputed in the background: a local model manages
    # ~14 chars/sec, so a chat export takes an hour — it must be ready before
    # the user opens the file, not while they wait for it.
    # "" = not looked at yet | pending (part-way) | done | not_needed
    translation_status: str = ""
    translation: str = ""
    # chunks already translated — a long document survives a restart instead of
    # starting over (and therefore never finishing)
    translation_chunks_done: int = 0


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


class Person(SQLModel, table=True):
    """A human in the case — the "who". Belongs to one case. May or may not
    appear in the investigation materials (in_evidence); the user can add
    people who don't (e.g. a suspect's brother) and describe who they are."""
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="case.id", index=True)
    name: str = Field(index=True)
    description: str = ""          # who they are / role, free text
    in_evidence: bool = True       # False = added manually, not in the materials
    created_at: datetime = Field(default_factory=utcnow)


class PersonLink(SQLModel, table=True):
    """Anything attached to a person. kind:
      alias     - a name/nickname that refers to this person (value)
      phone     - a phone number (value)
      photo     - an image evidence (evidence_id, value = optional caption)
      relation  - a tie to another person (related_person_id, value = type
                  e.g. 'אח', 'אבא של', 'חבר קרוב')"""
    id: Optional[int] = Field(default=None, primary_key=True)
    person_id: int = Field(foreign_key="person.id", index=True)
    kind: str = Field(index=True)
    value: str = ""
    evidence_id: Optional[int] = Field(default=None, foreign_key="evidence.id")
    related_person_id: Optional[int] = Field(default=None, foreign_key="person.id")
    confidence: float = 1.0        # < 1.0 = system suggestion pending confirm (ב2)
    created_at: datetime = Field(default_factory=utcnow)


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


class WatchlistItem(SQLModel, table=True):
    """A standing query: a name/phone/keyword the lawyer wants flagged in every
    piece of evidence — including material that finishes processing weeks from
    now (36k voice notes are transcribing in the background)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: Optional[int] = Field(default=None, foreign_key="case.id", index=True)
    term: str = Field(index=True)
    # phone terms match digits-normalized ("0524657474" hits "052-465-7474")
    kind: str = "text"  # text | phone
    created_at: datetime = Field(default_factory=utcnow)


class WatchlistHit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    watchlist_item_id: int = Field(foreign_key="watchlistitem.id", index=True)
    evidence_id: int = Field(foreign_key="evidence.id", index=True)
    chunk_index: int = 0
    snippet: str = ""              # the match in context
    seen: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Story(SQLModel, table=True):
    """An investigation notebook (Timesketch-style): a titled sequence of notes,
    pinned evidence and saved searches that builds an argument — e.g. 'סתירות
    בגרסת המתלונן' — and can later feed a report."""
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="case.id", index=True)
    title: str
    created_at: datetime = Field(default_factory=utcnow)


class StoryItem(SQLModel, table=True):
    """One block in a story. kind:
      note     - free text (content = the text)
      evidence - a pinned evidence (evidence_id, content = why it matters)
      search   - a saved query (content = the query string)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    story_id: int = Field(foreign_key="story.id", index=True)
    kind: str = "note"
    content: str = ""
    evidence_id: Optional[int] = Field(default=None, foreign_key="evidence.id")
    position: int = 0
    created_at: datetime = Field(default_factory=utcnow)
