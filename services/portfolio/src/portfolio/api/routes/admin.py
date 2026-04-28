"""Admin / operator routes for the Portfolio service.

F-204 (QA iter-2): exposes a manual ``recompute today's snapshot`` trigger so
an operator can rebuild the portfolio_value_snapshots row after a holdings
mutation (e.g. ``repair_holdings_after_replay_drift`` --force, or after a
manual data fix). Without this, a snapshot written before the mutation stays
in the time-series, and the equity curve disagrees with every other surface
on the page.

Auth: same ``InternalJWTMiddleware`` as the rest of S1. The route accepts any
authenticated user for now — we intentionally don't gate on a "role=admin"
claim because the auth-roles wiring is not yet finished (PRD-0025 deferred
admin tier). Operators run this through the gateway with their own JWT and
the route's idempotent design (an upsert) means accidental re-invocation is
harmless.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from portfolio.api.dependencies import UoWDep
from portfolio.application.use_cases.compute_portfolio_value import (
    ComputePortfolioValueCommand,
    ComputePortfolioValueUseCase,
)
from portfolio.workers.portfolio_snapshot_worker import HttpOHLCVPriceClient

router = APIRouter(tags=["admin"], prefix="/admin")


class RecomputeSnapshotResponse(BaseModel):
    """Result of a manual snapshot recompute."""

    portfolio_id: UUID
    snapshot_date: str
    total_value: str
    total_cost: str
    cash_value: str


def _extract_tenant_id(request: Request) -> UUID:
    """Read tenant_id from the verified JWT (set by InternalJWTMiddleware)."""
    raw = getattr(request.state, "tenant_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing tenant_id in JWT")
    return UUID(str(raw))


@router.post(
    "/portfolios/{portfolio_id}/recompute-snapshot",
    response_model=RecomputeSnapshotResponse,
    status_code=status.HTTP_200_OK,
)
async def recompute_snapshot(
    portfolio_id: UUID,
    uow: UoWDep,
    request: Request,
) -> RecomputeSnapshotResponse:
    """Recompute today's portfolio_value_snapshots row for ``portfolio_id``.

    Idempotent: the underlying ``ComputePortfolioValueUseCase`` upserts on
    ``(portfolio_id, snapshot_date)`` so re-invocation simply overwrites
    today's row with a freshly computed value. Empty portfolios (no
    holdings) write a $0 row — operators relying on F-210's "skip empty"
    semantics should verify holdings exist before triggering the recompute.

    F-204 (QA iter-2): paired with the ``repair_holdings_after_replay_drift``
    script's snapshot deletion. After running ``--force`` and zeroing
    holdings, an operator hits this endpoint to write today's snapshot
    against the new (zeroed) state, eliminating the equity-curve / KPI
    contradiction the iter-1 audit observed.
    """
    tenant_id = _extract_tenant_id(request)

    # Validate the portfolio belongs to the tenant before doing any work —
    # surfaces 404 instead of leaking existence to other tenants.
    portfolio = await uow.portfolios.get(portfolio_id, tenant_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Build the price client off the request's app.state — the snapshot
    # worker constructs an HTTP-backed client at startup, but the API
    # process doesn't carry one. Construct an ephemeral client per request:
    # admin recompute is a low-frequency operator action, so the cost of a
    # short-lived AsyncClient is acceptable. Lifespan-scoped reuse can
    # land in a follow-up.
    settings = request.app.state.settings
    today = datetime.now(tz=UTC).date()

    async with httpx.AsyncClient(timeout=10.0) as http:
        price_client = HttpOHLCVPriceClient(
            http=http,
            market_data_url=settings.market_data_service_url,
        )
        use_case = ComputePortfolioValueUseCase(price_client)
        snapshot = await use_case.execute(
            ComputePortfolioValueCommand(
                portfolio_id=portfolio_id,
                tenant_id=tenant_id,
                as_of_date=today,
            ),
            uow,
        )
        await uow.commit()

    return RecomputeSnapshotResponse(
        portfolio_id=portfolio_id,
        snapshot_date=today.isoformat(),
        # Decimal serialisation parity with every other Decimal-on-the-wire
        # field in this service (8-dp string).
        total_value=f"{snapshot.total_value:.8f}",
        total_cost=f"{snapshot.total_cost:.8f}",
        cash_value=f"{snapshot.cash_value:.8f}",
    )
