"""FastAPI dependency injection helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from fastapi import Depends, Request

if TYPE_CHECKING:
    from market_data.application.ports.uow import UnitOfWork
    from market_data.application.use_cases.query_fundamental_metrics import (
        GetAvailableFundamentalMetricsUseCase,
        GetFundamentalMetricsTimeseriesUseCase,
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
    from market_data.application.use_cases.query_quotes import GetQuotesBatchUseCase, GetQuoteUseCase
    from market_data.application.use_cases.query_securities import GetSecurityUseCase, ListSecuritiesUseCase
    from market_data.infrastructure.cache.quote_cache import QuoteCache


# ── Core infrastructure deps ──────────────────────────────────────────────────


async def get_uow(request: Request) -> AsyncIterator[UnitOfWork]:
    """Yield an open SqlAlchemyUnitOfWork for the duration of the request."""
    from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork

    write_factory = request.app.state.write_session_factory
    read_factory = request.app.state.read_session_factory
    async with SqlAlchemyUnitOfWork(write_factory, read_factory) as uow:
        yield uow


async def get_quote_cache(request: Request) -> QuoteCache:
    """Return the QuoteCache bound to this application instance."""
    return request.app.state.quote_cache  # type: ignore[no-any-return]


# ── Instrument use case deps ──────────────────────────────────────────────────


def get_instrument_by_id_uc(uow: UnitOfWork = Depends(get_uow)) -> GetInstrumentByIdUseCase:
    from market_data.application.use_cases.query_instruments import GetInstrumentByIdUseCase

    return GetInstrumentByIdUseCase(uow)


def get_instrument_by_symbol_uc(uow: UnitOfWork = Depends(get_uow)) -> GetInstrumentBySymbolUseCase:
    from market_data.application.use_cases.query_instruments import GetInstrumentBySymbolUseCase

    return GetInstrumentBySymbolUseCase(uow)


def get_search_instruments_uc(uow: UnitOfWork = Depends(get_uow)) -> SearchInstrumentsUseCase:
    from market_data.application.use_cases.query_instruments import SearchInstrumentsUseCase

    return SearchInstrumentsUseCase(uow)


# ── Security use case deps ────────────────────────────────────────────────────


def get_security_uc(uow: UnitOfWork = Depends(get_uow)) -> GetSecurityUseCase:
    from market_data.application.use_cases.query_securities import GetSecurityUseCase

    return GetSecurityUseCase(uow)


def get_list_securities_uc(uow: UnitOfWork = Depends(get_uow)) -> ListSecuritiesUseCase:
    from market_data.application.use_cases.query_securities import ListSecuritiesUseCase

    return ListSecuritiesUseCase(uow)


# ── Quote use case deps ───────────────────────────────────────────────────────


def get_quote_uc(uow: UnitOfWork = Depends(get_uow)) -> GetQuoteUseCase:
    from market_data.application.use_cases.query_quotes import GetQuoteUseCase

    return GetQuoteUseCase(uow)


def get_quotes_batch_uc(uow: UnitOfWork = Depends(get_uow)) -> GetQuotesBatchUseCase:
    from market_data.application.use_cases.query_quotes import GetQuotesBatchUseCase

    return GetQuotesBatchUseCase(uow)


# ── OHLCV use case deps ───────────────────────────────────────────────────────


def get_ohlcv_bars_uc(uow: UnitOfWork = Depends(get_uow)) -> GetOHLCVBarsUseCase:
    from market_data.application.use_cases.query_ohlcv import GetOHLCVBarsUseCase

    return GetOHLCVBarsUseCase(uow)


def get_ohlcv_bulk_uc(uow: UnitOfWork = Depends(get_uow)) -> GetOHLCVBulkUseCase:
    from market_data.application.use_cases.query_ohlcv import GetOHLCVBulkUseCase

    return GetOHLCVBulkUseCase(uow)


def get_available_timeframes_uc(uow: UnitOfWork = Depends(get_uow)) -> GetAvailableTimeframesUseCase:
    from market_data.application.use_cases.query_ohlcv import GetAvailableTimeframesUseCase

    return GetAvailableTimeframesUseCase(uow)


def get_ohlcv_range_uc(uow: UnitOfWork = Depends(get_uow)) -> GetOHLCVRangeUseCase:
    from market_data.application.use_cases.query_ohlcv import GetOHLCVRangeUseCase

    return GetOHLCVRangeUseCase(uow)


# ── Fundamentals use case deps ────────────────────────────────────────────────


def get_fundamentals_section_uc(uow: UnitOfWork = Depends(get_uow)) -> GetFundamentalsSectionUseCase:
    from market_data.application.use_cases.query_fundamentals import GetFundamentalsSectionUseCase

    return GetFundamentalsSectionUseCase(uow)


# ── Fundamental metrics use case deps ─────────────────────────────────────────


def get_timeseries_uc(uow: UnitOfWork = Depends(get_uow)) -> GetFundamentalMetricsTimeseriesUseCase:
    from market_data.application.use_cases.query_fundamental_metrics import (
        GetFundamentalMetricsTimeseriesUseCase,
    )

    return GetFundamentalMetricsTimeseriesUseCase(uow)


def get_screen_instruments_uc(uow: UnitOfWork = Depends(get_uow)) -> ScreenInstrumentsUseCase:
    from market_data.application.use_cases.query_fundamental_metrics import ScreenInstrumentsUseCase

    return ScreenInstrumentsUseCase(uow)


def get_available_metrics_uc(uow: UnitOfWork = Depends(get_uow)) -> GetAvailableFundamentalMetricsUseCase:
    from market_data.application.use_cases.query_fundamental_metrics import (
        GetAvailableFundamentalMetricsUseCase,
    )

    return GetAvailableFundamentalMetricsUseCase(uow)
