"""Pydantic request/response models for S5 API endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ── DLQ ──────────────────────────────────────────────────────────────────────


class DLQEntryResponse(BaseModel):
    dlq_id: UUID
    original_event_id: UUID
    topic: str
    error_detail: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None


class DLQListResponse(BaseModel):
    entries: list[DLQEntryResponse]
    count: int


class DLQResolveRequest(BaseModel):
    note: str = Field(..., max_length=2000)


# ── Batch documents ───────────────────────────────────────────────────────────


class BatchDocumentsRequest(BaseModel):
    # max_length not enforced here — use case raises DomainError (→ 400) for >50
    doc_ids: list[UUID] = Field(..., min_length=1)


class DocumentMetadataResponse(BaseModel):
    doc_id: UUID
    title: str | None
    url: str | None
    published_at: datetime | None
    source_name: str | None
    source_type: str | None
    word_count: int | None


class BatchDocumentsResponse(BaseModel):
    documents: list[DocumentMetadataResponse]
