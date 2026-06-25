"""Portfolio API routes.

Auth: InternalJWTMiddleware sets request.state.tenant_id / user_id from the
verified RS256 JWT. Routes read these values from request.state, never from
raw headers (PRD-0025, F-CRIT-001 remediation).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import Response

from portfolio.api.dependencies import ReadUoWDep, UoWDep
from portfolio.api.schemas import (
    ConcentrationResponse,
    ExposureResponse,
    HoldingLotItem,
    HoldingLotsResponse,
    PaginatedResponse,
    PortfolioCreateRequest,
    PortfolioPatchRequest,
    PortfolioRenameRequest,
    PortfolioResponse,
    RealizedPnLResponse,
    TopPositionItem,
    TwrPointResponse,
    TwrResponse,
    ValueHistoryMetadata,
    ValueHistoryPoint,
    ValueHistoryResponse,
)
from portfolio.api.schemas import (
    RealizedPnLBreakdownItem as RealizedPnLBreakdownItemResponse,
)
from portfolio.application.use_cases.compute_concentration import (
    ComputeConcentrationQuery,
    ComputeConcentrationUseCase,
)
from portfolio.application.use_cases.compute_twr import ComputeTwrQuery, ComputeTwrUseCase
from portfolio.application.use_cases.create_portfolio import CreatePortfolioCommand, CreatePortfolioUseCase
from portfolio.application.use_cases.get_exposure import GetExposureQuery, GetExposureUseCase
from portfolio.application.use_cases.get_holding_lots import (
    GetHoldingLotsQuery,
    GetHoldingLotsUseCase,
)
from portfolio.application.use_cases.get_realized_pnl import (
    GetRealizedPnLQuery,
    GetRealizedPnLUseCase,
    default_from_date,
    default_to_date,
)
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
    UpdatePortfolioCommand,
    UpdatePortfolioUseCase,
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
        # PLAN-0114 W6: surface cost_basis_method.
        cost_basis_method=str(portfolio.cost_basis_method),
    )


@router.post("/portfolios", response_model=PortfolioResponse)
async def create_portfolio(
    body: PortfolioCreateRequest,
    uow: UoWDep,
    request: Request,
    response: Response,
    # REQ-002a (TASK-W0-02): caller-supplied ``Idempotency-Key`` for safe
    # retries. Matches the header alias used by POST /v1/transactions so
    # the frontend retry config can target one consistent header name.
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> PortfolioResponse:
    """Create a new portfolio.

    Status codes:
        201 — new portfolio created (no replay).
        200 — idempotent replay returned the previously-created portfolio
              (caller sent the same ``Idempotency-Key`` they used earlier).
        409 — idempotency key reuse with a different request body.
        422 — idempotency key is not a valid UUID.
    """
    x_tenant_id = _extract_tenant_id(request)
    uc = CreatePortfolioUseCase()
    result = await uc.execute(
        CreatePortfolioCommand(
            tenant_id=x_tenant_id,
            owner_id=body.owner_user_id,
            name=body.name,
            currency=body.currency,
            idempotency_key=idempotency_key,
        ),
        uow,
    )
    # REQ-002a: set the status code explicitly here instead of via the
    # decorator so an idempotent replay can return 200 while a fresh create
    # returns 201 — the OpenAPI docs declare 201 as the default response.
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return _to_response(result.portfolio)


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


@router.patch("/portfolios/{portfolio_id}", response_model=PortfolioResponse)
async def patch_portfolio(
    portfolio_id: UUID,
    body: PortfolioPatchRequest,
    uow: UoWDep,
    request: Request,
) -> PortfolioResponse:
    """PLAN-0114 W6 / T-W6-01: partial-update portfolio settings.

    Currently supports: ``cost_basis_method`` (FIFO | AVCO).
    Fields omitted from the body are not touched.
    """
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    from portfolio.domain.enums import CostBasisMethod  # local import avoids circular

    uc = UpdatePortfolioUseCase()
    portfolio = await uc.execute(
        UpdatePortfolioCommand(
            portfolio_id=portfolio_id,
            owner_id=owner_id,
            tenant_id=x_tenant_id,
            cost_basis_method=CostBasisMethod(body.cost_basis_method) if body.cost_basis_method else None,
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


# ── Flow-adjusted TWR (2026-06-10 frontend-enhancement sprint, gap #3) ─────────


@router.get("/portfolios/{portfolio_id}/twr", response_model=TwrResponse)
async def get_twr(
    portfolio_id: UUID,
    uow: ReadUoWDep,
    request: Request,
    days: int = Query(default=90, ge=1, le=3650),
) -> TwrResponse:
    """Return the daily flow-adjusted time-weighted-return series.

    Replaces the frontend's NAV-relative approximation: TWR computes
    sub-period returns between external cash flows (transactions) and
    geometrically links them, so deposits/withdrawals/trades no longer
    masquerade as performance. Formula, flow-classification rules and
    edge-case handling are documented in :class:`ComputeTwrUseCase`.

    Window: ``[today - days, today]`` (UTC). NAV points come from the
    daily ``portfolio_value_snapshots``; flows from ``transactions``.

    Returns 404 (standard exception handler) when the portfolio is
    missing, in another tenant, or owned by another user.

    R27: read-only path → ``ReadOnlyUnitOfWork``.
    """
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)

    today = datetime.now(tz=UTC).date()
    start = today - timedelta(days=days)

    uc = ComputeTwrUseCase()
    result = await uc.execute(
        ComputeTwrQuery(
            portfolio_id=portfolio_id,
            owner_id=owner_id,
            tenant_id=x_tenant_id,
            from_date=start,
            to_date=today,
        ),
        uow,
    )

    return TwrResponse(
        portfolio_id=result.portfolio_id,
        from_date=result.from_date,
        to_date=result.to_date,
        points=[TwrPointResponse(date=p.date, twr_cum_pct=p.twr_cum_pct, nav=p.nav) for p in result.points],
        flow_days=result.flow_days,
        flow_dates=result.flow_dates,
    )


# ── PLAN-0051 Wave A — realised P&L ───────────────────────────────────────────


@router.get(
    "/portfolios/{portfolio_id}/realized-pnl",
    response_model=RealizedPnLResponse,
)
async def get_realized_pnl(
    portfolio_id: UUID,
    uow: ReadUoWDep,
    request: Request,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
) -> RealizedPnLResponse:
    """Compute realised P&L (FIFO) for a portfolio over ``[from, to]``.

    PLAN-0051 / T-A-1-04. Powers the new "Realised P&L" KPI on the
    portfolio page. The use case walks the FULL transaction history so
    cost basis is correct even when the requested window starts long
    after the original BUYs — see the use-case docstring for the
    algorithm and edge-case handling.

    Defaults match the YTD convention used elsewhere in the product:

    * ``from`` defaults to the first day of the current UTC year.
    * ``to`` defaults to today UTC.

    Returns 404 (via the standard exception handler) if the portfolio
    doesn't exist, isn't in the caller's tenant, or isn't owned by them.

    R27: depends on :class:`ReadOnlyUnitOfWork` (read replica).
    """
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)

    today = datetime.now(tz=UTC).date()
    start = from_date if from_date is not None else default_from_date(today)
    end = to_date if to_date is not None else default_to_date(today)
    if start > end:
        raise HTTPException(status_code=400, detail="`from` must be on or before `to`")

    uc = GetRealizedPnLUseCase()
    result = await uc.execute(
        GetRealizedPnLQuery(
            portfolio_id=portfolio_id,
            owner_id=owner_id,
            tenant_id=x_tenant_id,
            from_date=start,
            to_date=end,
        ),
        uow,
    )

    return RealizedPnLResponse(
        total_realized=result.total_realized,
        realized_long_term=result.realized_long_term,
        realized_short_term=result.realized_short_term,
        count=result.count,
        breakdown_by_instrument=[
            RealizedPnLBreakdownItemResponse(
                instrument_id=row.instrument_id,
                ticker=row.ticker,
                name=row.name,
                realized=row.realized,
            )
            for row in result.breakdown_by_instrument
        ],
        currency=result.currency,
        from_date=result.from_date,
        to_date=result.to_date,
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
        # 2026-06-10 gap #5: v1 buying_power == cash (no margin modelled).
        buying_power=result.buying_power,
    )


# ── PLAN-0088 Wave E — Holdings redesign ──────────────────────────────────────


@router.get(
    "/portfolios/{portfolio_id}/holdings/{instrument_id}/lots",
    response_model=HoldingLotsResponse,
)
async def get_holding_lots(
    portfolio_id: UUID,
    instrument_id: UUID,
    uow: ReadUoWDep,
    request: Request,
    current_price: Decimal | None = Query(
        default=None,
        description=(
            "Optional current price override. When supplied, each lot's"
            " ``unrealised_pnl`` is computed as qty*(current_price -"
            " cost_per_share). When omitted the field is null and the UI"
            " renders '—'."
        ),
    ),
) -> HoldingLotsResponse:
    """PLAN-0088 E-2 — return open FIFO lots for one holding.

    Powers the holdings-table expand-row drill-down. Lots are oldest-first,
    each with open-date / quantity / cost-per-share / days-held / ST-or-LT
    classification (365-day boundary) and an optional unrealised P&L.

    Authorisation matches the other portfolio reads — 404 when the
    portfolio is missing, in another tenant, or owned by another user.

    R27: read-only path → ``ReadOnlyUnitOfWork``.
    """
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)

    uc = GetHoldingLotsUseCase()
    result = await uc.execute(
        GetHoldingLotsQuery(
            portfolio_id=portfolio_id,
            instrument_id=instrument_id,
            owner_id=owner_id,
            tenant_id=x_tenant_id,
            current_price=current_price,
        ),
        uow,
    )

    return HoldingLotsResponse(
        portfolio_id=result.portfolio_id,
        instrument_id=result.instrument_id,
        lots=[
            HoldingLotItem(
                open_date=lot.open_date,
                qty=lot.qty,
                cost_per_share=lot.cost_per_share,
                days_held=lot.days_held,
                is_long_term=lot.is_long_term,
                unrealised_pnl=lot.unrealised_pnl,
            )
            for lot in result.lots
        ],
        total_qty=result.total_qty,
        total_cost=result.total_cost,
        long_term_qty=result.long_term_qty,
        short_term_qty=result.short_term_qty,
        as_of=result.as_of,
    )


@router.get(
    "/portfolios/{portfolio_id}/concentration",
    response_model=ConcentrationResponse,
)
async def get_concentration(
    portfolio_id: UUID,
    uow: ReadUoWDep,
    request: Request,
) -> ConcentrationResponse:
    """PLAN-0088 E-3 — Herfindahl-Hirschman concentration metrics.

    Returns HHI (0-10,000), a "diversified|moderate|concentrated|empty"
    label, top-3 cumulative weight, and the 5 largest positions for the
    UI's ConcentrationStrip row. Empty portfolios return HHI=0/label="empty".

    Uses the live price client when available; falls back to cost basis
    per holding when individual quotes are missing (``prices_stale`` flips
    True so the frontend can label the row as estimated).

    R27: read-only path → ``ReadOnlyUnitOfWork``.
    """
    owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)

    # Reuse the same shared HTTP-backed price client from app.state. Pooled
    # connection lifetime; constructed once at lifespan startup.
    price_client = request.app.state.current_price_client

    uc = ComputeConcentrationUseCase(price_client=price_client)
    result = await uc.execute(
        ComputeConcentrationQuery(
            portfolio_id=portfolio_id,
            owner_id=owner_id,
            tenant_id=x_tenant_id,
        ),
        uow,
    )

    return ConcentrationResponse(
        portfolio_id=result.portfolio_id,
        hhi=result.hhi,
        label=result.label,
        top_3_share_pct=result.top_3_share_pct,
        positions_count=result.positions_count,
        top_positions=[
            TopPositionItem(instrument_id=p.instrument_id, weight_pct=p.weight_pct) for p in result.top_positions
        ],
        prices_stale=result.prices_stale,
    )
