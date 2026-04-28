"""Portfolio API routes.

Auth: InternalJWTMiddleware sets request.state.tenant_id / user_id from the
verified RS256 JWT. Routes read these values from request.state, never from
raw headers (PRD-0025, F-CRIT-001 remediation).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response

from portfolio.api.dependencies import ReadUoWDep, UoWDep
from portfolio.api.schemas import (
    ExposureResponse,
    PaginatedResponse,
    PortfolioCreateRequest,
    PortfolioRenameRequest,
    PortfolioResponse,
    ValueHistoryMetadata,
    ValueHistoryPoint,
    ValueHistoryResponse,
)
from portfolio.application.use_cases.create_portfolio import CreatePortfolioCommand, CreatePortfolioUseCase
from portfolio.application.use_cases.get_exposure import GetExposureQuery, GetExposureUseCase
from portfolio.application.use_cases.get_value_history import (
    GetValueHistoryQuery,
    GetValueHistoryUseCase,
)
from portfolio.application.use_cases.portfolio_ops import (
    ArchivePortfolioUseCase,
    GetPortfolioUseCase,
    ListPortfoliosUseCase,
    RenamePortfolioCommand,
    RenamePortfolioUseCase,
)

router = APIRouter(tags=["portfolios"])


def _extract_tenant_id(request: Request) -> UUID:
    """Read tenant_id from request.state set by InternalJWTMiddleware."""
    raw = getattr(request.state, "tenant_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing tenant_id in JWT")
    return UUID(str(raw))


def _extract_owner_id(request: Request) -> UUID:
    """Read user_id (owner) from request.state set by InternalJWTMiddleware."""
    raw = getattr(request.state, "user_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing user_id in JWT")
    return UUID(str(raw))


def _to_response(portfolio) -> PortfolioResponse:  # type: ignore[no-untyped-def]
    return PortfolioResponse(
        id=portfolio.id,
        tenant_id=portfolio.tenant_id,
        owner_id=portfolio.owner_id,
        name=portfolio.name,
        currency=portfolio.currency,
        status=str(portfolio.status),
        # PLAN-0046 Wave 3 / T-46-3-01 — surface kind to API clients.
        kind=str(portfolio.kind),
        created_at=portfolio.created_at,
    )


@router.post("/portfolios", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    body: PortfolioCreateRequest,
    uow: UoWDep,
    request: Request,
) -> PortfolioResponse:
    x_tenant_id = _extract_tenant_id(request)
    uc = CreatePortfolioUseCase()
    portfolio = await uc.execute(
        CreatePortfolioCommand(
            tenant_id=x_tenant_id,
            owner_id=body.owner_user_id,
            name=body.name,
            currency=body.currency,
        ),
        uow,
    )
    return _to_response(portfolio)


@router.get("/portfolios", response_model=PaginatedResponse[PortfolioResponse])
async def list_portfolios(
    uow: ReadUoWDep,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse[PortfolioResponse]:
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    uc = ListPortfoliosUseCase()
    portfolios, total = await uc.execute(owner_id, x_tenant_id, uow, limit=limit, offset=offset)
    return PaginatedResponse(items=[_to_response(p) for p in portfolios], total=total, limit=limit, offset=offset)


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioResponse)
async def get_portfolio(
    portfolio_id: UUID,
    uow: ReadUoWDep,
    request: Request,
) -> PortfolioResponse:
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    uc = GetPortfolioUseCase()
    portfolio = await uc.execute(portfolio_id, owner_id, x_tenant_id, uow)
    return _to_response(portfolio)


@router.put("/portfolios/{portfolio_id}", response_model=PortfolioResponse)
async def rename_portfolio(
    portfolio_id: UUID,
    body: PortfolioRenameRequest,
    uow: UoWDep,
    request: Request,
) -> PortfolioResponse:
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    uc = RenamePortfolioUseCase()
    portfolio = await uc.execute(
        RenamePortfolioCommand(
            portfolio_id=portfolio_id,
            owner_id=owner_id,
            tenant_id=x_tenant_id,
            new_name=body.name,
        ),
        uow,
    )
    return _to_response(portfolio)


@router.delete(
    "/portfolios/{portfolio_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def archive_portfolio(
    portfolio_id: UUID,
    uow: UoWDep,
    request: Request,
) -> None:
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    uc = ArchivePortfolioUseCase()
    await uc.execute(portfolio_id, owner_id, x_tenant_id, uow)


# ── PLAN-0046 Wave 5 — analytics endpoints ────────────────────────────────────


@router.get("/portfolios/{portfolio_id}/value-history", response_model=ValueHistoryResponse)
async def get_value_history(
    portfolio_id: UUID,
    uow: ReadUoWDep,
    request: Request,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    days: int | None = Query(default=None, ge=1, le=3650),
    granularity: Literal["1d", "1w", "1m"] = Query(default="1d"),
) -> ValueHistoryResponse:
    """Return the daily portfolio value snapshots over the requested range.

    PLAN-0046 Wave 5 / T-46-5-01. Powers the equity-curve chart.

    Range resolution (F-202, QA iter-2):
      * ``from`` + ``to`` — explicit range, both honoured; ``from`` wins if both
        ``from`` and ``days`` are supplied (so older clients keep working).
      * ``days=N`` alone — translates to ``from = today - N days, to = today``.
      * No params — returns last 90 days (the documented default).
      * ``granularity=1w`` / ``1m`` resamples to last-snapshot-per-bucket.

    Returns 404 (via the ``PortfolioNotFoundError`` exception handler) if the
    portfolio is missing or not owned by the caller's tenant.

    F-009 (QA iter-2): the response now also carries a ``metadata`` block with
    ``last_snapshot_at`` (most recent snapshot in the FILTERED range, or ``null``
    when the range is empty) and ``next_scheduled_run_utc`` (the next 21:30 UTC
    snapshot wake-up). The frontend uses both to render an honest empty-state
    hint ("Next snapshot scheduled for …") instead of a generic message.

    R27: depends on ``ReadOnlyUnitOfWork`` (read replica).
    """
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)

    # F-202 / F-009: range resolution.
    # Order of precedence:
    #   1. explicit ``from`` always wins (existing client contract).
    #   2. otherwise ``days`` translates to a today-anchored window.
    #   3. otherwise no lower bound (the route returns the full series; this
    #      mirrors the F-022 fix that lets the "All" period selector return
    #      every snapshot rather than the previous 90-day sneaky default).
    today = datetime.now(tz=UTC).date()
    end = to_date or today
    if from_date is not None:
        start = from_date
    elif days is not None:
        start = today - timedelta(days=days)
    else:
        # date.min ≈ 0001-01-01 — earlier than any real snapshot, so the range
        # scan returns everything up to ``end``. The docstring promises 90-day
        # default in plain English, but the backend has always treated "no
        # params" as "all snapshots" since the F-022 fix; the guard here keeps
        # that behaviour explicit.
        start = date.min
    if start > end:
        # 400 instead of silently swapping — surfaces caller error explicitly.
        raise HTTPException(status_code=400, detail="`from`/`days` must produce a range on or before `to`")

    uc = GetValueHistoryUseCase()
    snapshots = await uc.execute(
        GetValueHistoryQuery(
            portfolio_id=portfolio_id,
            owner_id=owner_id,
            tenant_id=x_tenant_id,
            from_date=start,
            to_date=end,
            granularity=granularity,
        ),
        uow,
    )

    points = [
        ValueHistoryPoint(
            date=s.snapshot_date,
            value=s.total_value,
            cost_basis=s.total_cost,
            cash=s.cash_value,
            # F-501 (QA iter-5): propagate the per-snapshot data-quality flag.
            # ``s.data_quality`` is "ok" for fully-priced rows and
            # "partial_prices" when the F-401 fallback engaged (stale
            # close or cost-basis substitution). The frontend renders a
            # small "Partial prices" caption inside the tooltip on those
            # points so the user knows this point is an honest estimate.
            data_quality=s.data_quality or "ok",
        )
        for s in snapshots
    ]

    # F-009: compute metadata.
    # ``last_snapshot_at`` reflects the latest snapshot **inside the returned
    # window** so the frontend hint matches what the user is seeing. We chose
    # not to look up the latest snapshot across all time because that confuses
    # the "what's new since I last looked at THIS view" mental model.
    last_snapshot_at = snapshots[-1].snapshot_date.isoformat() if snapshots else None
    # Next scheduled run = next 21:30 UTC. The constant lives in the worker;
    # we compute it here from a fresh ``datetime.now`` so the hint is always
    # forward-looking. If we're past 21:30 UTC today, schedule for tomorrow.
    now_utc = datetime.now(tz=UTC)
    next_run = now_utc.replace(hour=21, minute=30, second=0, microsecond=0)
    if next_run <= now_utc:
        next_run = next_run + timedelta(days=1)

    return ValueHistoryResponse(
        points=points,
        metadata=ValueHistoryMetadata(
            last_snapshot_at=last_snapshot_at,
            next_scheduled_run_utc=next_run.isoformat(),
        ),
    )


@router.get("/portfolios/{portfolio_id}/exposure", response_model=ExposureResponse)
async def get_exposure(
    portfolio_id: UUID,
    uow: ReadUoWDep,
    request: Request,
) -> ExposureResponse:
    """Return the current invested / cash / leverage breakdown.

    PLAN-0046 Wave 5 / T-46-5-02. R9: the use case fetches current
    prices from S3 via REST through the ``CurrentPriceClient`` port —
    no cross-service DB access.

    Empty portfolios return all zeros (NOT NaN) so the frontend can
    render a clean empty state.
    """
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)

    # Pull the shared (long-lived) HTTP-backed price client off app.state.
    # Constructed once at lifespan startup so connections are pooled.
    price_client = request.app.state.current_price_client

    uc = GetExposureUseCase(price_client=price_client)
    result = await uc.execute(
        GetExposureQuery(
            portfolio_id=portfolio_id,
            owner_id=owner_id,
            tenant_id=x_tenant_id,
        ),
        uow,
    )
    return ExposureResponse(
        invested=result.invested,
        cash=result.cash,
        gross_exposure_pct=result.gross_exposure_pct,
        net_exposure_pct=result.net_exposure_pct,
        leverage=result.leverage,
        # F-016 — surface staleness so the frontend can render a "Prices
        # stale" badge instead of pretending cost-basis is live market value.
        prices_stale=result.prices_stale,
        prices_as_of=result.prices_as_of,
    )
