"""Instruments API router."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from market_data.api.dependencies import (
    get_instrument_by_id_uc,
    get_instrument_by_symbol_uc,
    get_search_instruments_uc,
)
from market_data.api.schemas.instruments import (
    InstrumentFlagsResponse,
    InstrumentListResponse,
    InstrumentResponse,
)
from market_data.application.use_cases.query_instruments import (
    GetInstrumentByIdUseCase,
    GetInstrumentBySymbolUseCase,
    SearchInstrumentsUseCase,
)
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
    uc: Annotated[GetInstrumentBySymbolUseCase, Depends(get_instrument_by_symbol_uc)] = ...,  # type: ignore[assignment]
) -> InstrumentResponse:
    """Return the instrument matching the given symbol (and optional exchange)."""
    instrument = await uc.execute(symbol, exchange)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Instrument not found: {symbol}/{exchange}")
    return _to_response(instrument)


@router.get("/instruments/{instrument_id}", response_model=InstrumentResponse)
async def get_instrument(
    instrument_id: Annotated[str, _INSTRUMENT_ID_PARAM],
    uc: Annotated[GetInstrumentByIdUseCase, Depends(get_instrument_by_id_uc)] = ...,  # type: ignore[assignment]
) -> InstrumentResponse:
    """Return the instrument with the given UUID."""
    instrument = await uc.execute(instrument_id)
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
    uc: Annotated[SearchInstrumentsUseCase, Depends(get_search_instruments_uc)] = ...,  # type: ignore[assignment]
) -> InstrumentListResponse:
    """List instruments with optional DB-side filters and pagination."""
    total, items = await uc.execute(
        query,
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
