"""Pydantic request/response models for the S4 API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ── Source CRUD ──────────────────────────────────────────────────────────────


class SourceResponse(BaseModel):
    id: UUID
    name: str
    source_type: str
    enabled: bool
    last_fetch_at: datetime | None = None


class SourceListResponse(BaseModel):
    sources: list[SourceResponse]


class SourceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    source_type: str = Field(..., min_length=1, max_length=50)
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class SourceUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    enabled: bool | None = None
    config: dict | None = None


class TriggerResponse(BaseModel):
    status: str = "triggered"
    source_id: UUID


# ── Status ───────────────────────────────────────────────────────────────────


class SourceStatusDetail(BaseModel):
    name: str
    last_fetch_at: datetime | None = None
    articles_fetched_24h: int = 0
    errors_24h: int = 0


class StatusResponse(BaseModel):
    sources: list[SourceStatusDetail]
    outbox_pending: int = 0
    dlq_count: int = 0


# ── Internal ingest submit ───────────────────────────────────────────────────


class IngestSubmitRequest(BaseModel):
    url: str | None = Field(None, max_length=4096)
    raw_content: str | None = Field(None, max_length=5_242_880)
    source_type: str = Field(..., min_length=1, max_length=50)
    title: str | None = Field(None, max_length=500)
    published_at: datetime | None = None


class IngestSubmitResponse(BaseModel):
    doc_id: UUID
    status: str = "accepted"


# ── DLQ ──────────────────────────────────────────────────────────────────────


class DLQEntryResponse(BaseModel):
    dlq_id: UUID
    original_event_id: UUID
    topic: str
    error_detail: str | None = None
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class DLQListResponse(BaseModel):
    entries: list[DLQEntryResponse]
    count: int


class DLQResolveRequest(BaseModel):
    note: str = Field(..., min_length=1, max_length=2000)


# ── Error ────────────────────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
