"""FastAPI dependency injection helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from market_data.application.ports.uow import ReadOnlyUnitOfWork, UnitOfWork

if TYPE_CHECKING:
    from market_data.application.ports.cache import QuoteCachePort, ScreenFieldsCachePort
    from market_data.application.use_cases.query_fundamental_metrics import (
        GetAvailableFundamentalMetricsUseCase,
        GetFundamentalMetricsTimeseriesUseCase,
        ScreenFieldsMetadataUseCase,
        ScreenInstrumentsUseCase,
    )
    from market_data.application.use_cases.query_fundamentals import GetFundamentalsSectionUseCase
    from market_data.application.use_cases.query_instruments import (
        GetInstrumentByIdUseCase,
        GetInstrumentBySymbolUseCase,
        SearchInstrumentsUseCase,
    )
    from market_data.application.use_cases.query_ohlcv import (
        GetAvailableTimeframesUseCase,
        GetOHLCVBarsUseCase,
        GetOHLCVBulkUseCase,
        GetOHLCVRangeUseCase,
    )
    from market_data.application.use_cases.query_prediction_markets import (
        GetPredictionMarketHistoryUseCase,
        GetPredictionMarketUseCase,
        ListPredictionMarketsUseCase,
    )
    from market_data.application.use_cases.query_quotes import GetQuotesBatchUseCase, GetQuoteUseCase
    from market_data.application.use_cases.query_securities import GetSecurityUseCase, ListSecuritiesUseCase


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


# ── Instrument use case deps ──────────────────────────────────────────────────


def get_instrument_by_id_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetInstrumentByIdUseCase:
    from market_data.application.use_cases.query_instruments import GetInstrumentByIdUseCase

    return GetInstrumentByIdUseCase(uow)


def get_instrument_by_symbol_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetInstrumentBySymbolUseCase:
    from market_data.application.use_cases.query_instruments import GetInstrumentBySymbolUseCase

    return GetInstrumentBySymbolUseCase(uow)


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


# ── Fundamentals use case deps ────────────────────────────────────────────────


def get_fundamentals_section_uc(uow: ReadOnlyUnitOfWork = Depends(get_read_uow)) -> GetFundamentalsSectionUseCase:
    from market_data.application.use_cases.query_fundamentals import GetFundamentalsSectionUseCase

    return GetFundamentalsSectionUseCase(uow)


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
