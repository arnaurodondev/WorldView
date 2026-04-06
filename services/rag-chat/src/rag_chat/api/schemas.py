"""Pydantic request/response schemas for the RAG-Chat API (T-D-4-02, T-F-4-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# ── Request schemas ───────────────────────────────────────────────────────────


class CreateThreadRequest(BaseModel):
    title: str | None = Field(None, max_length=200)
    entity_ids: list[UUID] = Field(default=[], max_length=5)


class ChatRequestSchema(BaseModel):
    """Request body for POST /api/v1/chat and POST /api/v1/chat/stream."""

    message: str = Field(..., min_length=1, max_length=2000)
    thread_id: UUID | None = None
    entity_ids: list[UUID] = Field(default=[], max_length=5)


class ChatResponse(BaseModel):
    """Synchronous chat response."""

    answer: str
    citations: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    thread_id: str | None = None
    message_id: str | None = None
    intent: str | None = None
    provider: str | None = None
    latency_ms: int | None = None


# ── Response schemas ──────────────────────────────────────────────────────────


class CreateThreadResponse(BaseModel):
    thread_id: UUID
    title: str | None
    created_at: datetime


class MessageResponse(BaseModel):
    message_id: UUID
    role: str
    content: str
    intent: str | None
    citations: list[dict[str, Any]]
    created_at: datetime


class ThreadSummaryResponse(BaseModel):
    thread_id: UUID
    title: str | None
    last_msg_at: datetime | None
    message_count: int
    entity_ids: list[UUID]
    created_at: datetime


class ThreadDetailResponse(BaseModel):
    thread_id: UUID
    title: str | None
    created_at: datetime
    messages: list[MessageResponse]


class PaginatedThreadsResponse(BaseModel):
    threads: list[ThreadSummaryResponse]
    total: int


class DeleteThreadResponse(BaseModel):
    thread_id: UUID
    archived_at: datetime
