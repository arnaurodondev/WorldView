"""Portfolio response schemas.

WHY: These Pydantic models mirror the TypeScript interfaces in
apps/worldview-web/types/api.ts (Portfolio).
GET /v1/portfolios proxies S1 and returns a list of Portfolio objects.
"""

from __future__ import annotations

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
