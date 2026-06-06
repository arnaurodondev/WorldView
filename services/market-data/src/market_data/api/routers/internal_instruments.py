"""Internal instruments API router — system-to-system endpoints.

Exposes:
  GET /internal/v1/instruments?exchange=US&limit=1000&offset=0
  GET /internal/v1/instruments/top-by-market-cap?n=500&offset=0

Mounted under ``/internal/v1`` so the path matches the other internal
endpoints (``price_snapshot``). All routes require ``X-Internal-JWT``;
``InternalJWTMiddleware`` provides the global guard, and
``require_internal_jwt`` is wired as an explicit route-level dependency so
unit tests can override it without standing up the full middleware stack.

WHY A SEPARATE ROUTER FILE (not extending ``instruments.py``):
the public ``instruments.py`` router is mounted at ``/api/v1``. Adding an
internal-only path inside it would require mounting the same router twice
or sprinkling ``/internal/v1`` literals inside path strings, both of which
fight FastAPI's prefix model.

PLAN-0100 T-W5-01.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from market_data.api.dependencies import get_search_instruments_uc, require_internal_jwt
from market_data.api.schemas.instruments import (
    InstrumentFlagsResponse,
    InstrumentListResponse,
    InstrumentResponse,
    OhlcvCoveredItem,
    OhlcvCoveredResponse,
    TopByMarketCapItem,
    TopByMarketCapResponse,
)
from market_data.application.use_cases.get_ohlcv_covered import (
    query_ohlcv_covered,
)
from market_data.application.use_cases.get_top_by_market_cap import (
    query_top_by_market_cap,
)
from market_data.application.use_cases.query_instruments import SearchInstrumentsUseCase
from market_data.domain.entities import Instrument

# IMPORTANT: no prefix here — ``app.include_router(internal_instruments.router,
# prefix="/internal/v1")`` adds the prefix at wire-up time so the file works
# the same way whether mounted under /internal/v1 (prod) or under a test
# prefix (unit tests).
router = APIRouter(tags=["internal-instruments"])


def _instrument_to_response(instrument: Instrument) -> InstrumentResponse:
    """Convert domain Instrument to API response schema.

    WHY duplicated from instruments.py: cross-importing between routers creates
    a circular dependency risk. The helper is trivial so a local copy is safer.
    """
    return InstrumentResponse(
        id=instrument.id,
        security_id=instrument.security_id,
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        is_active=instrument.is_active,
        flags=InstrumentFlagsResponse(
            has_ohlcv=instrument.flags.has_ohlcv,
            has_quotes=instrument.flags.has_quotes,
            has_fundamentals=instrument.flags.has_fundamentals,
        ),
        created_at=instrument.created_at,
    )


@router.get(
    "/instruments",
    response_model=InstrumentListResponse,
)
async def list_instruments_internal(
    exchange: Annotated[
        str | None,
        Query(description="Filter by exchange code (e.g. 'US', 'CC')."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=5000, description="Page size. Max 5000."),
    ] = 1000,
    offset: Annotated[
        int,
        Query(ge=0, description="Pagination offset."),
    ] = 0,
    _: Annotated[None, Depends(require_internal_jwt)] = None,
    uc: Annotated[SearchInstrumentsUseCase, Depends(get_search_instruments_uc)] = ...,  # type: ignore[assignment]
) -> InstrumentListResponse:
    """List instruments with optional exchange filter — internal service-to-service use only.

    WHY THIS EXISTS (PLAN-0106): InstrumentPolicySyncWorker (S2) and
    TickerNewsSymbolSyncWorker (S4) need to enumerate active instruments by
    exchange to create or update per-ticker polling policies and news sources.
    The public ``GET /api/v1/instruments`` requires a user JWT; this internal
    variant accepts an ``X-Internal-JWT`` signed by sibling services.

    Auth: ``X-Internal-JWT`` required — enforced by both InternalJWTMiddleware
    (global) and the explicit ``require_internal_jwt`` dep (unit-test safety).
    """
    total, items = await uc.execute(
        # Empty query string = no symbol/exchange substring filter; we use the
        # dedicated exchange= kwarg for exact exchange filtering.
        "",
        exchange=exchange,
        limit=limit,
        offset=offset,
    )
    return InstrumentListResponse(
        items=[_instrument_to_response(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/instruments/top-by-market-cap",
    response_model=TopByMarketCapResponse,
)
async def get_top_by_market_cap(
    request: Request,
    n: Annotated[
        int,
        Query(
            ge=1,
            le=5000,
            description=(
                "How many instruments to return. Clamped to [1, 5000]. "
                "Default 500 matches FundamentalsRefreshWorker's default top_n."
            ),
        ),
    ] = 500,
    offset: Annotated[
        int,
        Query(ge=0, description="Pagination offset; clients walk pages with offset += n."),
    ] = 0,
    _: Annotated[None, Depends(require_internal_jwt)] = None,
) -> TopByMarketCapResponse:
    """Return the top-N active instruments sorted by latest market cap.

    Sorted descending on ``market_cap_usd`` with NULLs last (instruments
    that have never had a fundamentals fetch). Within the NULL bucket the
    order is stable by symbol.

    Auth: ``X-Internal-JWT`` is required. ``InternalJWTMiddleware`` rejects
    requests without a valid header at 401 before reaching this handler;
    the explicit ``require_internal_jwt`` dep is a belt-and-braces guard
    for unit tests that bypass the middleware stack.
    """
    # WHY raw session (not ReadUoW): the query is one SELECT with no repo
    # boundaries to honour. Following the precedent set by
    # ``get_fundamentals_snapshot_uc`` (see dependencies.py), we just take a
    # session out of the read factory. This keeps the use case decoupled
    # from infrastructure (no ORM imports) and the router unchanged when the
    # ORM model evolves.
    read_factory = request.app.state.read_session_factory
    async with read_factory() as session:
        total, rows = await query_top_by_market_cap(session, n=n, offset=offset)

    results = [
        TopByMarketCapItem(
            id=str(row["id"]),
            symbol=row["symbol"],
            exchange=row["exchange"],
            # ``value_numeric`` comes back as ``Decimal`` from asyncpg. Cast to
            # float here so the JSON response is numeric (not a stringified
            # decimal); precision loss at the cent level is acceptable for
            # market-cap values that span billions.
            market_cap_usd=(float(row["market_cap_usd"]) if row.get("market_cap_usd") is not None else None),
            currency_code=row.get("currency_code"),
        )
        for row in rows
    ]
    return TopByMarketCapResponse(
        total=total,
        offset=offset,
        limit=n,
        results=results,
    )


@router.get(
    "/instruments/ohlcv-covered",
    response_model=OhlcvCoveredResponse,
)
async def get_ohlcv_covered(
    request: Request,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=5000,
            description=(
                "How many instruments to return per page. Clamped to [1, 5000]. "
                "Default 1000 — most callers (market-ingestion universe loader) "
                "want the full set and will page until exhausted."
            ),
        ),
    ] = 1000,
    offset: Annotated[
        int,
        Query(ge=0, description="Pagination offset; clients walk pages with offset += limit."),
    ] = 0,
    _: Annotated[None, Depends(require_internal_jwt)] = None,
) -> OhlcvCoveredResponse:
    """Return instruments with ``has_ohlcv = TRUE``, ordered by symbol ASC.

    PLAN-0089 Wave L-4b. Used by market-ingestion's insider-transactions
    universe loader to replace the hardcoded 3-ticker seed
    (AAPL/TSLA/AMZN) with the live OHLCV-covered universe (~3000 tickers
    at full coverage; ~24k EODHD credits/month at weekly polling).

    Auth: ``X-Internal-JWT`` required (same model as get_top_by_market_cap).
    """
    read_factory = request.app.state.read_session_factory
    async with read_factory() as session:
        total, rows = await query_ohlcv_covered(session, limit=limit, offset=offset)

    results = [
        OhlcvCoveredItem(
            id=str(row["id"]),
            symbol=row["symbol"],
            exchange=row["exchange"],
            country=row.get("country"),
            currency_code=row.get("currency_code"),
        )
        for row in rows
    ]
    return OhlcvCoveredResponse(
        total=total,
        offset=offset,
        limit=limit,
        results=results,
    )
