"""Fundamentals and earnings-calendar response schemas.

WHY: These Pydantic models mirror the S3 FundamentalsResponse shape and the
S7 TemporalEventsListResponse shape proxied through S9.

GET /v1/fundamentals/{id} → S3 → FundamentalsResponse:
    {security_id: str, records: list[FundamentalsRecordResponse]}
    Where each record has: id, security_id, section, period_end,
    period_type, data (dict), source, ingested_at.

GET /v1/fundamentals/earnings-calendar → S7 temporal-events (event_type=corporate):
    {events: list[TemporalEventResponse], total: int}
    Where each event has: event_id, event_type, scope, region, title,
    description, active_from, active_until, confidence, etc.

These Python schemas are intentionally independent of the TypeScript types to
avoid tight coupling — the TS side uses EarningsEvent/EarningsCalendarResponse
which are hand-written until the OpenAPI spec is fully annotated.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

# ── Fundamentals (GET /v1/fundamentals/{id}) ─────────────────────────────────


class FundamentalsRecord(BaseModel):
    """One fundamentals data record for a given section and period.

    Mirrors S3 FundamentalsRecordResponse.
    WHY data is dict: EODHD fundamentals sections (Highlights, Technicals,
    ShareStatistics, etc.) each have different key-value structures. Typing as
    dict[str, Any] with extra=allow passes the raw data through without loss.
    """

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    security_id: str | None = None
    section: str | None = None  # e.g. "technicals_snapshot", "earnings_history"
    period_end: str | None = None  # ISO 8601 date from S3
    period_type: str | None = None  # "ANNUAL" | "QUARTERLY" | "SNAPSHOT"
    data: dict[str, Any] | None = None  # Section-specific key-value pairs
    source: str | None = None
    ingested_at: str | None = None  # ISO 8601 UTC datetime


class FundamentalsResponse(BaseModel):
    """All fundamentals records for a security (all sections).

    Mirrors S3 FundamentalsResponse. Proxied by GET /v1/fundamentals/{id}.

    WHY security_id (not instrument_id): S3 uses security_id as its primary
    identifier (mapped from instrument_id at ingestion time). The frontend
    joins via the instrument overview response.

    WHY records list: S3 stores each EODHD section as a separate row so
    different section types can have different period cadences (daily
    technicals vs annual income statements).
    """

    model_config = ConfigDict(extra="allow")

    security_id: str
    records: list[FundamentalsRecord] = []


# ── Earnings Calendar (GET /v1/fundamentals/earnings-calendar) ───────────────


class EarningsEvent(BaseModel):
    """A single corporate earnings event from S7 temporal-events.

    Mirrors the S7 TemporalEventResponse schema (knowledge-graph service)
    filtered to event_type=corporate by the proxy route.

    WHY region = ticker: The EarningsCalendarDatasetConsumer (13D-9) stores
    the company ticker symbol in `region` because temporal_events.region is
    a free-text label. Frontend extracts the ticker from this field.

    WHY active_from / active_until (not report_date): S7 uses a lifecycle
    model where active_from = report datetime and active_until = residual
    impact end (typically active_from + 7 days).
    """

    model_config = ConfigDict(extra="allow")

    event_id: str
    event_type: str | None = None  # "corporate" for earnings events
    scope: str | None = None
    region: str | None = None  # Ticker symbol, e.g. "AAPL"
    title: str | None = None  # e.g. "AAPL Q3 2026 Earnings"
    description: str | None = None  # e.g. "EPS est. $1.45 (BMO)"
    active_from: str | None = None  # ISO 8601 UTC — report datetime
    active_until: str | None = None  # ISO 8601 UTC — residual end (+7 days)
    confidence: float | None = None  # Always 1.0 for confirmed dates
    lifecycle_phase: str | None = None  # "upcoming" | "active" | "residual"
    exposed_entity_count: int | None = None


class EarningsCalendarResponse(BaseModel):
    """Response from GET /v1/fundamentals/earnings-calendar.

    Mirrors S7 TemporalEventsListResponse with event_type=corporate filter.
    WHY total: S7 returns total for pagination support even when limit is
    applied. Frontend renders "showing N of M events".
    """

    model_config = ConfigDict(extra="allow")

    events: list[EarningsEvent] = []
    total: int = 0
