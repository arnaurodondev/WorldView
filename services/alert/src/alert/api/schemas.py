"""Pydantic request/response schemas for the Alert service API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

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
    severity: str  # "low" | "medium" | "high" | "critical" (PRD-0021 §6.5)


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

    note: str = Field(default="", max_length=2000, description="Resolution note")


# ── Email Preferences ─────────────────────────────────────────────────────────


class EmailPreferencesResponse(BaseModel):
    """Response schema for GET/PUT /api/v1/email/preferences."""

    user_id: UUID
    weekly_digest_enabled: bool
    send_day_of_week: int = Field(ge=0, le=6)
    send_hour_utc: int = Field(ge=0, le=23)
    email_address: EmailStr | None
    last_digest_sent_at: datetime | None


class UpdateEmailPreferencesRequest(BaseModel):
    """Request body for PUT /api/v1/email/preferences."""

    weekly_digest_enabled: bool | None = None
    send_day_of_week: int | None = Field(default=None, ge=0, le=6)
    send_hour_utc: int | None = Field(default=None, ge=0, le=23)
    email_address: EmailStr | None = Field(default=..., description="Delivery address; null clears override")


class DigestTriggerRequest(BaseModel):
    """Request body for POST /admin/email/digest/trigger."""

    user_id: UUID
    tenant_id: UUID


class DigestTriggerResponse(BaseModel):
    """Response for POST /admin/email/digest/trigger."""

    job_id: UUID
    status: str = "queued"
