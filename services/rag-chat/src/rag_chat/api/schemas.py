"""Pydantic request/response schemas for the RAG-Chat API (T-D-4-02)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# ── Request schemas ───────────────────────────────────────────────────────────


class CreateThreadRequest(BaseModel):
    title: str | None = Field(None, max_length=200)
    entity_ids: list[UUID] = Field(default=[], max_length=5)


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
