"""Instruments API router."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from market_data.api.dependencies import get_uow
from market_data.api.schemas.instruments import (
    InstrumentFlagsResponse,
    InstrumentListResponse,
    InstrumentResponse,
)
from market_data.application.ports.uow import UnitOfWork
from market_data.domain.entities import Instrument

router = APIRouter(tags=["instruments"])

_INSTRUMENT_ID_PARAM = Path(description="Instrument UUID (primary key of the ``instruments`` table).")


def _to_response(instrument: Instrument) -> InstrumentResponse:
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


# IMPORTANT: literal-path route must be declared BEFORE the path-param route
@router.get("/instruments/symbol/{symbol}", response_model=InstrumentResponse)
async def get_instrument_by_symbol(
    symbol: str,
    exchange: str = "",
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> InstrumentResponse:
    """Return the instrument matching the given symbol (and optional exchange)."""
    instrument = await uow.instruments_read.find_by_symbol_exchange(symbol, exchange)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Instrument not found: {symbol}/{exchange}")
    return _to_response(instrument)


@router.get("/instruments/{instrument_id}", response_model=InstrumentResponse)
async def get_instrument(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> InstrumentResponse:
    """Return the instrument with the given UUID."""
    instrument = await uow.instruments_read.find_by_id(instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Instrument not found: {instrument_id}")
    return _to_response(instrument)


@router.get("/instruments", response_model=InstrumentListResponse)
async def list_instruments(
    query: Annotated[str, Query(description="Symbol/exchange substring search")] = "",
    has_ohlcv: Annotated[bool | None, Query(description="Filter by OHLCV data availability")] = None,
    has_quotes: Annotated[bool | None, Query(description="Filter by quote data availability")] = None,
    has_fundamentals: Annotated[bool | None, Query(description="Filter by fundamentals data availability")] = None,
    exchange: Annotated[str | None, Query(description="Filter by exchange code")] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="Page size")] = 100,
    offset: Annotated[int, Query(ge=0, description="Page offset")] = 0,
    uow: Annotated[UnitOfWork, Depends(get_uow)] = ...,  # type: ignore[assignment]
) -> InstrumentListResponse:
    """List instruments with optional DB-side filters and pagination."""
    repo = uow.instruments_read
    total, items = await _search_with_count(
        repo,
        query=query,
        has_ohlcv=has_ohlcv,
        has_quotes=has_quotes,
        has_fundamentals=has_fundamentals,
        exchange=exchange,
        limit=limit,
        offset=offset,
    )
    return InstrumentListResponse(
        items=[_to_response(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


async def _search_with_count(repo, *, query, has_ohlcv, has_quotes, has_fundamentals, exchange, limit, offset):  # type: ignore[no-untyped-def]
    """Run count + search in two DB queries (avoids loading all rows for pagination)."""
    filter_kwargs = {
        "has_ohlcv": has_ohlcv,
        "has_quotes": has_quotes,
        "has_fundamentals": has_fundamentals,
        "exchange": exchange,
    }
    total = await repo.count(query, **filter_kwargs)
    items = await repo.search(query, **filter_kwargs, limit=limit, offset=offset)
    return total, items
