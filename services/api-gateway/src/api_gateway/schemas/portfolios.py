"""Portfolio response schemas.

WHY: These Pydantic models mirror the TypeScript interfaces in
apps/worldview-web/types/api.ts (Portfolio).
GET /v1/portfolios proxies S1 and returns a list of Portfolio objects.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class PortfolioResponse(BaseModel):
    """A single portfolio.

    Mirrors the Portfolio TypeScript interface in types/api.ts.
    WHY kind is optional: older S1 builds may not emit the kind discriminator
    field (added in PLAN-0046 Wave 3). Once all deployments include it,
    this can become required.
    """

    model_config = ConfigDict(extra="allow")

    portfolio_id: str
    name: str
    kind: str | None = None
    currency: str | None = None
    tenant_id: str | None = None


class SectorBucket(BaseModel):
    """One sector row in a portfolio sector attribution response."""

    model_config = ConfigDict(extra="allow")

    sector: str
    holding_count: int = 0
    market_value: float = 0.0
    sector_weight_pct: float = 0.0  # weight as 0-100
    sector_day_pnl: float = 0.0  # unrealised day P&L in portfolio currency


class PortfolioSectorAttributionResponse(BaseModel):
    """Response for GET /v1/portfolios/{id}/sector-attribution."""

    model_config = ConfigDict(extra="allow")

    portfolio_id: str
    buckets: list[SectorBucket] = []
    covered_pct: float = 0.0  # fraction of portfolio (by market value) with sector data


class SectorBreakdownSegment(BaseModel):
    """One segment in the optimised sector-breakdown response.

    Returned by GET /v1/portfolios/{id}/sector-breakdown (single-query variant).
    """

    model_config = ConfigDict(extra="allow")

    sector: str
    weight: float = 0.0  # fraction 0-1 of total market value
    count: int = 0  # number of holdings in this sector
    market_value: float = 0.0  # absolute market value in portfolio currency
    # 2026-06-10 (frontend-enhancement sprint, gap #2): the instrument UUIDs
    # belonging to this segment. Lets the frontend map sector filters back to
    # holdings rows by id instead of a fragile name-alias join. Defaulted []
    # so older cached responses without the field still validate.
    instrument_ids: list[str] = []


class SectorBreakdownResponse(BaseModel):
    """Response for GET /v1/portfolios/{id}/sector-breakdown.

    Single-aggregation-query variant — guaranteed < 300ms because it performs
    at most 2 downstream HTTP calls (holdings + price batch) with sector data
    read from the instruments table via parallel instrument-lookup calls.
    """

    model_config = ConfigDict(extra="allow")

    portfolio_id: str
    segments: list[SectorBreakdownSegment] = []
    covered_pct: float = 0.0  # fraction of portfolio MV that has a known sector
    as_of: date | None = None  # server-side date of the response


class PortfolioBundleResponse(BaseModel):
    """Portfolio page bundle — all data needed for the portfolio page initial load.

    PLAN-0070 C-1: collapses 4 portfolio page requests into one round-trip.
    Each leg is independently nullable — partial=True in bundle_meta when
    any downstream call failed.

    WHY extra="allow": the bundle passes through upstream fields as-is;
    new S1 fields added in future don't need a schema update here.
    WHY bundle_meta (not _meta): Pydantic v2 treats leading-underscore field
    names as private attributes — they cannot be declared as model fields.
    The client function returns "_meta" as a dict key which extra="allow"
    captures automatically. bundle_meta serves as the validated alias form.
    """

    model_config = ConfigDict(extra="allow")

    portfolio_id: str
    portfolio: dict | None = None
    holdings: dict | None = None
    transactions: dict | None = None
    value_history: dict | None = None
    bundle_meta: dict | None = None
