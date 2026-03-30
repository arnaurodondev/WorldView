"""Pydantic request/response schemas for the Alert service API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ── Pending Alerts ────────────────────────────────────────────────────────────


class PendingAlertResponse(BaseModel):
    """A single pending (unacknowledged) alert for a user."""

    pending_id: UUID
    alert_id: UUID
    entity_id: UUID
    alert_type: str
    source_topic: str
    payload: dict  # type: ignore[type-arg]
    created_at: datetime


class PendingAlertsResponse(BaseModel):
    """Paginated list of pending alerts."""

    alerts: list[PendingAlertResponse]
    total: int
    limit: int
    offset: int


# ── DLQ Admin ────────────────────────────────────────────────────────────────


class DLQEntryResponse(BaseModel):
    """A single dead-letter-queue entry."""

    dlq_id: UUID
    original_event_id: UUID
    topic: str
    error_detail: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None


class DLQListResponse(BaseModel):
    """Paginated list of DLQ entries."""

    entries: list[DLQEntryResponse]
    total: int


class DLQResolveRequest(BaseModel):
    """Request body for resolving a DLQ entry."""

    note: str = Field(default="", description="Resolution note")
