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
