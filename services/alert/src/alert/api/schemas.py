"""Pydantic request/response schemas for the Alert service API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

# ── L-5a active-alert flag (PLAN-0089 Wave L-5a) ─────────────────────────────


class ActiveAlertFlagResponse(BaseModel):
    """Per-entity active-alert summary for the screener S3-side sync worker.

    "Active" means: exists at least one ``alerts`` row whose ``entity_id``
    matches the instrument, ``acknowledged_at IS NULL``, and
    ``snooze_until`` is either NULL or in the past (audit §8.a option a).
    """

    instrument_id: UUID
    has_active_alert: bool
    active_alert_count: int = Field(ge=0)


# ── Pending Alerts ────────────────────────────────────────────────────────────


class PendingAlertResponse(BaseModel):
    """A single pending (unacknowledged) alert for a user.

    PLAN-0049 T-A-1-02 / T-D-4-04: surface the persisted enrichment fields
    (title, ticker, entity_name, signal_label) so the frontend never has to
    fall back to bare-severity strings like ``"LOW signal"`` (F-D-006).
    All four are optional for forward-compat — old rows persist NULL.
    """

    pending_id: UUID
    alert_id: UUID
    entity_id: UUID
    alert_type: str
    source_topic: str
    payload: dict  # type: ignore[type-arg]
    created_at: datetime
    severity: str  # "low" | "medium" | "high" | "critical" (PRD-0021 §6.5)
    title: str | None = None
    ticker: str | None = None
    entity_name: str | None = None
    signal_label: str | None = None


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


# ── Alert acknowledgement / snooze / history (PLAN-0051 T-D-4-02) ─────────────


class AcknowledgeAlertRequest(BaseModel):
    """Body for ``PATCH /api/v1/alerts/{alert_id}/acknowledge``.

    ``note`` is informational only and not currently persisted (reserved for a
    future audit_log table). Accepted today so frontends can already pass it
    forward-compatibly.
    """

    # Optional free-text note describing why the alert was acked.
    note: str | None = Field(default=None, max_length=2000)


class SnoozeAlertRequest(BaseModel):
    """Body for ``PATCH /api/v1/alerts/{alert_id}/snooze``.

    ``until`` MUST be timezone-aware and in the future, no more than 30 days
    out (enforced server-side in SnoozeAlertUseCase, not Pydantic, because
    the upper bound depends on ``utc_now()`` at request time).
    """

    until: datetime


class AlertResponse(BaseModel):
    """Full alert response — used by ack/snooze responses + history list."""

    alert_id: UUID
    entity_id: UUID
    alert_type: str
    source_topic: str
    payload: dict  # type: ignore[type-arg]
    created_at: datetime
    severity: str  # "low" | "medium" | "high" | "critical"
    tenant_id: UUID | None
    title: str | None = None
    ticker: str | None = None
    entity_name: str | None = None
    signal_label: str | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by_user_id: UUID | None = None
    snooze_until: datetime | None = None


# ── User-initiated alert creation (PLAN-0082 Wave B) ──────────────────────────


class CreateAlertRequest(BaseModel):
    """Request body for ``POST /api/v1/alerts``.

    ``condition`` identifies the trigger type. ``threshold`` holds
    condition-specific parameters (e.g. ``{"value": 200.0}``). Both are
    required — a condition without a threshold cannot be evaluated.

    ``entity_id`` is the UUID of the entity to watch.  It is required
    because alert rules are always entity-scoped (no global alerts).
    """

    entity_id: UUID = Field(description="UUID of the entity to watch")
    condition: str = Field(
        description="Trigger condition: price_below | price_above | volume_spike | percent_change",
        min_length=1,
        max_length=100,
    )
    threshold: dict = Field(  # type: ignore[type-arg]
        description="JSON threshold parameters, e.g. {'value': 200.0}"
    )
    severity: str = Field(
        default="low",
        description="Initial severity tier: low | medium | high | critical",
    )


class AlertCreatedResponse(BaseModel):
    """Response body for ``POST /api/v1/alerts`` on success."""

    alert_id: UUID
    entity_id: UUID
    condition: str
    threshold: dict  # type: ignore[type-arg]
    severity: str
    created_at: str  # ISO-8601 UTC


class AlertHistoryResponse(BaseModel):
    """Paginated list of alerts in a tenant's history."""

    alerts: list[AlertResponse]
    # ``total`` is the universe count for the filtered tenant history (every
    # row matching the same filters), NOT the page size. Frontends use
    # ``rows.length < total`` to detect more-pages-available. QA-iter1 C-3
    # changed this from page-size semantics to universe semantics so the
    # "Load more" affordance actually appears.
    total: int
    limit: int
    offset: int
    # ``has_more`` is computed as ``offset + len(alerts) < total`` server-side
    # so the client can render "Load more" without re-deriving it.
    has_more: bool


# ── Alert Rules (PLAN-0113) ───────────────────────────────────────────────────


class AlertRuleCreateRequest(BaseModel):
    """Request body for POST /api/v1/alert-rules.

    ``condition`` is a raw dict validated against the discriminated union for
    ``rule_type`` in the route handler (so we can return a precise 400/422 with
    the field-level detail rather than a generic body-validation error).
    ``tenant_id``/``user_id`` are NEVER in the body — they come from the JWT.
    """

    rule_type: str = Field(description="One of PRICE_CROSS|NEWS_COUNT|NEWS_MOMENTUM|KG_CONNECTION|FUNDAMENTAL_CROSS")
    name: str | None = Field(default=None, max_length=255)
    condition: dict  # type: ignore[type-arg]
    severity: str = Field(default="medium", description="low|medium|high|critical")
    enabled: bool = True
    cooldown_seconds: int | None = Field(default=None, ge=0, le=604800)
    notify_in_app: bool = True
    notify_email: bool = False


class AlertRuleUpdateRequest(BaseModel):
    """Partial-update body for PATCH /api/v1/alert-rules/{rule_id}.

    All fields optional — only provided fields change. ``rule_type`` is
    immutable (omitted here). Changing ``condition`` re-arms the rule
    (``last_state`` reset to null).
    """

    name: str | None = Field(default=None, max_length=255)
    condition: dict | None = None  # type: ignore[type-arg]
    severity: str | None = Field(default=None, description="low|medium|high|critical")
    enabled: bool | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0, le=604800)
    notify_in_app: bool | None = None
    notify_email: bool | None = None


class AlertRuleResponse(BaseModel):
    """Full stored representation of an alert rule."""

    rule_id: UUID
    tenant_id: UUID
    user_id: UUID
    rule_type: str
    name: str
    entity_id: UUID | None
    node_a_entity_id: UUID | None
    node_b_entity_id: UUID | None
    condition: dict  # type: ignore[type-arg]
    severity: str
    enabled: bool
    cooldown_seconds: int
    notify_in_app: bool
    notify_email: bool
    last_state: dict | None  # type: ignore[type-arg]
    created_at: datetime
    updated_at: datetime


class AlertRuleListResponse(BaseModel):
    """Paginated list of the caller's alert rules."""

    items: list[AlertRuleResponse]
    total: int
