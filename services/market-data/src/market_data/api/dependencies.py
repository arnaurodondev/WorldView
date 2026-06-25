"""FastAPI dependency injection helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException, Request

from market_data.application.ports.uow import ReadOnlyUnitOfWork, UnitOfWork

if TYPE_CHECKING:
    from market_data.application.ports.cache import QuoteCachePort, ScreenFieldsCachePort
    from market_data.application.use_cases.get_fundamentals_history import GetFundamentalsHistoryUseCase
    from market_data.application.use_cases.get_ohlcv_bars_flexible import GetOHLCVBarsFlexibleUseCase
    from market_data.application.use_cases.get_period_movers import GetPeriodMoversUseCase
    from market_data.application.use_cases.get_sector_returns import GetSectorReturnsUseCase
    from market_data.application.use_cases.lookup_instrument import InstrumentLookupUseCase
    from market_data.application.use_cases.on_demand_profile import OnDemandProfileUseCase
    from market_data.application.use_cases.query_fundamental_metrics import (
        GetAvailableFundamentalMetricsUseCase,
        GetFundamentalMetricsTimeseriesUseCase,
        ScreenFieldsMetadataUseCase,
        ScreenInstrumentsUseCase,
    )
    from market_data.application.use_cases.query_fundamentals import GetFundamentalsSectionUseCase
    from market_data.application.use_cases.query_instruments import (
        SearchInstrumentsUseCase,
    )
    from market_data.application.use_cases.query_ohlcv import (
        GetAvailableTimeframesUseCase,
        GetOHLCVBarsUseCase,
        GetOHLCVBulkUseCase,
        GetOHLCVRangeUseCase,
    )
    from market_data.application.use_cases.query_prediction_markets import (
        CountPredictionMarketCategoriesUseCase,
        GetPredictionMarketHistoryUseCase,
        GetPredictionMarketUseCase,
        ListPredictionMarketsUseCase,
    )
    from market_data.application.use_cases.query_quote_stats import (
        GetIntradayStatsUseCase,
        GetMultiPeriodReturnsUseCase,
        GetPriceLevelsUseCase,
    )
    from market_data.application.use_cases.query_quotes import GetQuotesBatchUseCase, GetQuoteUseCase
    from market_data.application.use_cases.query_securities import GetSecurityUseCase, ListSecuritiesUseCase
    from market_data.infrastructure.cache.price_snapshot_cache import PriceSnapshotCache
    from market_data.infrastructure.eodhd.client import EodhHdClient


# ── Core infrastructure deps ──────────────────────────────────────────────────


async def get_uow(request: Request) -> AsyncIterator[UnitOfWork]:
    """Yield an open SqlAlchemyUnitOfWork for the duration of the request."""
    from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork

    write_factory = request.app.state.write_session_factory
    read_factory = request.app.state.read_session_factory
    async with SqlAlchemyUnitOfWork(write_factory, read_factory) as uow:
        yield uow


async def get_read_uow(request: Request) -> AsyncIterator[ReadOnlyUnitOfWork]:
    """Yield an open SqlAlchemyReadOnlyUnitOfWork for the duration of the request (R27)."""
    from market_data.infrastructure.db.uow import SqlAlchemyReadOnlyUnitOfWork

    read_factory = request.app.state.read_session_factory
    async with SqlAlchemyReadOnlyUnitOfWork(read_factory) as uow:
        yield uow


# Type aliases for dependency injection (R27)
UoWDep = Annotated[UnitOfWork, Depends(get_uow)]
ReadUoWDep = Annotated[ReadOnlyUnitOfWork, Depends(get_read_uow)]


async def get_quote_cache(request: Request) -> QuoteCachePort:
    """Return the QuoteCachePort bound to this application instance."""
    return request.app.state.quote_cache  # type: ignore[no-any-return]


async def get_screen_fields_cache(request: Request) -> ScreenFieldsCachePort:
    """Return the ScreenFieldsCachePort bound to this application instance."""
    return request.app.state.screen_fields_cache  # type: ignore[no-any-return]


async def get_price_snapshot_cache(request: Request) -> PriceSnapshotCache:
    """Return the PriceSnapshotCache bound to this application instance."""
    return request.app.state.price_snapshot_cache  # type: ignore[no-any-return]


# ── EODHD client dep ─────────────────────────────────────────────────────────


async def get_eodhd_client(request: Request) -> EodhHdClient:
    """Return the EodhHdClient singleton stored in app state."""
    return request.app.state.eodhd_client  # type: ignore[no-any-return]


# ── Internal JWT guard dep ────────────────────────────────────────────────────


async def require_internal_jwt(request: Request) -> None:
    """Belt-and-suspenders guard: raises 401 if X-Internal-JWT header is absent.

    The global InternalJWTMiddleware already enforces this, but having an
    explicit route-level dependency makes unit tests simpler — tests can
    override this dep without spinning up the full middleware stack.
    """
    if "x-internal-jwt" not in request.headers:
        raise HTTPException(status_code=401, detail="X-Internal-JWT header required")


# ── Instrument use case deps ──────────────────────────────────────────────────


def get_lookup_instrument_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> InstrumentLookupUseCase:
    from market_data.application.use_cases.lookup_instrument import InstrumentLookupUseCase

    return InstrumentLookupUseCase(uow)


def get_on_demand_profile_uc(
    request: Request,
    eodhd_client: EodhHdClient = Depends(get_eodhd_client),
) -> OnDemandProfileUseCase:
    """Inject a UoW factory (not a single open UoW) so the use case can run
    a 3-phase R25 pattern: read (UoW #1) → HTTP (no UoW) → write (UoW #2).

    F-D02: holding one UoW across the EODHD call would keep a DB session
    open for ~10 s under EODHD's worst-case latency, exhausting the pool.
    """
    from market_data.application.use_cases.on_demand_profile import OnDemandProfileUseCase
    from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork

    write_factory = request.app.state.write_session_factory
    read_factory = request.app.state.read_session_factory

    def uow_factory() -> UnitOfWork:
        # Build a brand-new UoW each call; caller is responsible for entering it.
        return SqlAlchemyUnitOfWork(write_factory, read_factory)

    return OnDemandProfileUseCase(uow_factory, eodhd_client)


def get_search_instruments_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> SearchInstrumentsUseCase:
    from market_data.application.use_cases.query_instruments import SearchInstrumentsUseCase

    return SearchInstrumentsUseCase(uow)


# ── Security use case deps ────────────────────────────────────────────────────


def get_security_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetSecurityUseCase:
    from market_data.application.use_cases.query_securities import GetSecurityUseCase

    return GetSecurityUseCase(uow)


def get_list_securities_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> ListSecuritiesUseCase:
    from market_data.application.use_cases.query_securities import ListSecuritiesUseCase

    return ListSecuritiesUseCase(uow)


# ── Quote use case deps ───────────────────────────────────────────────────────


def get_quote_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetQuoteUseCase:
    from market_data.application.use_cases.query_quotes import GetQuoteUseCase

    return GetQuoteUseCase(uow)


def get_quotes_batch_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetQuotesBatchUseCase:
    from market_data.application.use_cases.query_quotes import GetQuotesBatchUseCase

    return GetQuotesBatchUseCase(uow)


# ── OHLCV use case deps ───────────────────────────────────────────────────────


def get_ohlcv_bars_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetOHLCVBarsUseCase:
    from market_data.application.use_cases.query_ohlcv import GetOHLCVBarsUseCase

    return GetOHLCVBarsUseCase(uow)


def get_ohlcv_bulk_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetOHLCVBulkUseCase:
    from market_data.application.use_cases.query_ohlcv import GetOHLCVBulkUseCase

    return GetOHLCVBulkUseCase(uow)


def get_available_timeframes_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetAvailableTimeframesUseCase:
    from market_data.application.use_cases.query_ohlcv import GetAvailableTimeframesUseCase

    return GetAvailableTimeframesUseCase(uow)


def get_ohlcv_range_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetOHLCVRangeUseCase:
    from market_data.application.use_cases.query_ohlcv import GetOHLCVRangeUseCase

    return GetOHLCVRangeUseCase(uow)


# ── Quote-tab statistics deps (B-Q-2 / B-Q-3 / B-Q-4) ────────────────────────


def get_intraday_stats_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetIntradayStatsUseCase:
    from market_data.application.use_cases.query_quote_stats import GetIntradayStatsUseCase

    return GetIntradayStatsUseCase(uow)


def get_multi_period_returns_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetMultiPeriodReturnsUseCase:
    from market_data.application.use_cases.query_quote_stats import GetMultiPeriodReturnsUseCase

    return GetMultiPeriodReturnsUseCase(uow)


def get_price_levels_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetPriceLevelsUseCase:
    from market_data.application.use_cases.query_quote_stats import GetPriceLevelsUseCase

    return GetPriceLevelsUseCase(uow)


# ── PLAN-0066 Wave G: temporal endpoint deps ──────────────────────────────────


def get_ohlcv_bars_flexible_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetOHLCVBarsFlexibleUseCase:
    from market_data.application.use_cases.get_ohlcv_bars_flexible import GetOHLCVBarsFlexibleUseCase

    return GetOHLCVBarsFlexibleUseCase(uow)


def get_fundamentals_history_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetFundamentalsHistoryUseCase:
    from market_data.application.use_cases.get_fundamentals_history import GetFundamentalsHistoryUseCase

    return GetFundamentalsHistoryUseCase(uow)


# PLAN-0104 W32: parameterised fundamentals projection use case.
def get_query_fundamentals_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> Any:
    from market_data.application.use_cases.query_fundamentals_metrics import QueryFundamentalsUseCase

    return QueryFundamentalsUseCase(uow)


# ── Fundamentals use case deps ────────────────────────────────────────────────


def get_fundamentals_section_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetFundamentalsSectionUseCase:
    from market_data.application.use_cases.query_fundamentals import GetFundamentalsSectionUseCase

    return GetFundamentalsSectionUseCase(uow)


async def get_fundamentals_snapshot_uc(request: Request) -> AsyncIterator[Any]:
    """Yield GetFundamentalsSnapshotUseCase backed by the read (replica) session.

    WHY async generator with yield: the use case needs an open AsyncSession
    for the lifetime of the request.  FastAPI dependency injection calls the
    generator, yields the use case, then resumes after the route handler
    finishes to close the session cleanly — same pattern as get_uow().

    WHY read_session_factory (not ReadOnlyUnitOfWork): the snapshot use case
    accepts an AsyncSession directly for simplicity (one SELECT, no repos needed).
    The read_session_factory is wired at app startup and points to the read
    replica when one is configured, satisfying R27.
    """
    from market_data.application.use_cases.query_fundamentals_snapshot import (
        GetFundamentalsSnapshotUseCase,
    )

    read_factory = request.app.state.read_session_factory
    async with read_factory() as session:
        yield GetFundamentalsSnapshotUseCase(session)


# ── Fundamental metrics use case deps ─────────────────────────────────────────


def get_timeseries_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetFundamentalMetricsTimeseriesUseCase:
    from market_data.application.use_cases.query_fundamental_metrics import (
        GetFundamentalMetricsTimeseriesUseCase,
    )

    return GetFundamentalMetricsTimeseriesUseCase(uow)


def get_screen_instruments_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> ScreenInstrumentsUseCase:
    from market_data.application.use_cases.query_fundamental_metrics import ScreenInstrumentsUseCase

    return ScreenInstrumentsUseCase(uow)


def get_available_metrics_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetAvailableFundamentalMetricsUseCase:
    from market_data.application.use_cases.query_fundamental_metrics import (
        GetAvailableFundamentalMetricsUseCase,
    )

    return GetAvailableFundamentalMetricsUseCase(uow)


def get_screen_fields_uc(
    request: Request,
    uow: ReadOnlyUnitOfWork = Depends(get_read_uow),
) -> ScreenFieldsMetadataUseCase:
    from market_data.application.use_cases.query_fundamental_metrics import ScreenFieldsMetadataUseCase

    cache: ScreenFieldsCachePort = request.app.state.screen_fields_cache
    return ScreenFieldsMetadataUseCase(uow=uow, cache=cache)


# ── Prediction market use case deps ──────────────────────────────────────────


def get_list_prediction_markets_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> ListPredictionMarketsUseCase:
    from market_data.application.use_cases.query_prediction_markets import ListPredictionMarketsUseCase

    return ListPredictionMarketsUseCase(uow)


def get_prediction_market_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetPredictionMarketUseCase:
    from market_data.application.use_cases.query_prediction_markets import GetPredictionMarketUseCase

    return GetPredictionMarketUseCase(uow)


def get_prediction_market_history_uc(
    uow: ReadOnlyUnitOfWork = Depends(get_read_uow),
) -> GetPredictionMarketHistoryUseCase:
    from market_data.application.use_cases.query_prediction_markets import GetPredictionMarketHistoryUseCase

    return GetPredictionMarketHistoryUseCase(uow)


def get_count_prediction_market_categories_uc(
    uow: ReadOnlyUnitOfWork = Depends(get_read_uow),
) -> CountPredictionMarketCategoriesUseCase:
    """PLAN-0053 T-C-3-05 — categories endpoint dependency."""
    from market_data.application.use_cases.query_prediction_markets import (
        CountPredictionMarketCategoriesUseCase,
    )

    return CountPredictionMarketCategoriesUseCase(uow)


# ── Period aggregation use case deps ─────────────────────────────────────────


def get_sector_returns_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetSectorReturnsUseCase:
    from market_data.application.use_cases.get_sector_returns import GetSectorReturnsUseCase

    return GetSectorReturnsUseCase(uow)


def get_period_movers_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetPeriodMoversUseCase:
    from market_data.application.use_cases.get_period_movers import GetPeriodMoversUseCase

    return GetPeriodMoversUseCase(uow)
