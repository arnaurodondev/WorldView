"""Pydantic request/response schemas for the NLP Pipeline REST API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ── Signal schemas ────────────────────────────────────────────────────────────


class SignalResponse(BaseModel):
    signal_id: UUID
    doc_id: UUID
    entity_id: UUID
    signal_type: str
    confidence: float
    evidence_text: str
    detected_at: datetime


class SignalListResponse(BaseModel):
    items: list[SignalResponse]
    total: int
    limit: int
    offset: int


# ── Entity search ─────────────────────────────────────────────────────────────


class EntitySearchResponse(BaseModel):
    entity_id: UUID
    canonical_name: str
    entity_type: str
    mention_count: int


class EntityListResponse(BaseModel):
    items: list[EntitySearchResponse]
    total: int
    limit: int
    offset: int


class EntityDetailResponse(BaseModel):
    entity_id: UUID
    canonical_name: str
    entity_type: str
    mention_count: int
    resolved_count: int  # auto-resolved mentions
    provisional_count: int  # unresolved / provisional


class EntityArticleResponse(BaseModel):
    doc_id: UUID
    source_type: str
    published_at: datetime | None
    routing_tier: str
    mention_count: int


class EntityArticlesResponse(BaseModel):
    entity_id: UUID
    items: list[EntityArticleResponse]
    total: int


# ── Vector search ─────────────────────────────────────────────────────────────


class VectorSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048)
    limit: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class VectorSearchHit(BaseModel):
    doc_id: UUID
    section_id: UUID
    score: float
    snippet: str


class VectorSearchResponse(BaseModel):
    query: str
    hits: list[VectorSearchHit]


# ── Reprocess ─────────────────────────────────────────────────────────────────


class ReprocessResponse(BaseModel):
    article_id: UUID
    status: str  # "queued" | "not_found"
    message: str


# ── DLQ schemas ───────────────────────────────────────────────────────────────


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
    total: int


class DLQResolveRequest(BaseModel):
    note: str = Field(default="", max_length=1024)
