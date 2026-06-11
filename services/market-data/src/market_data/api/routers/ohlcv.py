"""OHLCV API router."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from market_data.api.dependencies import (
    get_available_timeframes_uc,
    get_lookup_instrument_uc,
    get_ohlcv_bars_flexible_uc,
    get_ohlcv_bars_uc,
    get_ohlcv_bulk_uc,
    get_ohlcv_range_uc,
)
from market_data.api.schemas.ohlcv import (
    OHLCVBarResponse,
    OHLCVBarsResponse,
    OHLCVFlexibleBar,
    OHLCVListResponse,
    OHLCVRangeResponse,
)
from market_data.application.use_cases.get_ohlcv_bars_flexible import GetOHLCVBarsFlexibleUseCase
from market_data.application.use_cases.lookup_instrument import InstrumentLookupUseCase
from market_data.application.use_cases.query_ohlcv import (
    GetAvailableTimeframesUseCase,
    GetOHLCVBarsUseCase,
    GetOHLCVBulkUseCase,
    GetOHLCVRangeUseCase,
)
from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.errors import InstrumentNotFoundError

router = APIRouter(tags=["ohlcv"])


def _to_bar_response(bar: OHLCVBar) -> OHLCVBarResponse:
    return OHLCVBarResponse(
        instrument_id=bar.instrument_id,
        timeframe=str(bar.timeframe),
        bar_date=bar.bar_date,
        open=str(bar.open),
        high=str(bar.high),
        low=str(bar.low),
        close=str(bar.close),
        volume=bar.volume,  # type: ignore[arg-type]  # Pydantic v2 plugin strict on int | None
        adjusted_close=str(bar.adjusted_close) if bar.adjusted_close is not None else None,
        source=bar.source,
    )


def _resolve_timeframe(timeframe_str: str) -> Timeframe:
    try:
        return Timeframe(timeframe_str)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid timeframe: {timeframe_str}")  # noqa: B904


def _validate_instrument_id(instrument_id: str) -> str:
    """Validate instrument_id is a UUID; raise 422 if not (prevents asyncpg DataError)."""
    try:
        UUID(instrument_id)
    except (ValueError, AttributeError):
        raise HTTPException(  # noqa: B904
            status_code=422,
            detail=f"Invalid instrument_id format: '{instrument_id}' — must be a UUID",
        )
    return instrument_id


# IMPORTANT: literal-path routes must come BEFORE {instrument_id} route
# PLAN-0066 Wave G: temporal RAG endpoint — GET /ohlcv/bars
@router.get("/ohlcv/bars", response_model=OHLCVBarsResponse)
async def get_ohlcv_bars_flexible(
    request: Request,
    instrument_id: Annotated[UUID | None, Query()] = None,
    symbol: Annotated[str | None, Query(min_length=1, max_length=20)] = None,
    isin: Annotated[str | None, Query(min_length=12, max_length=12)] = None,
    from_date: date = ...,  # type: ignore[assignment]
    to_date: date = ...,  # type: ignore[assignment]
    interval: str = Query(default="day", pattern="^(1m|5m|15m|30m|1h|4h|day|week|month)$"),
    max_bars: int = Query(default=252, ge=1, le=1000),
    uc: Annotated[GetOHLCVBarsFlexibleUseCase, Depends(get_ohlcv_bars_flexible_uc)] = ...,  # type: ignore[assignment]
    lookup_uc: Annotated[InstrumentLookupUseCase, Depends(get_lookup_instrument_uc)] = ...,  # type: ignore[assignment]
) -> OHLCVBarsResponse:
    """Return OHLCV bars for an instrument over a flexible date range (PLAN-0066 Wave G).

    WHY this endpoint: The brief-intelligence and temporal RAG pipelines need a
    finance-ready endpoint that accepts ticker/isin/UUID identifiers and returns
    plain float values (not Decimal strings) ordered ASC by date with interval
    resampling (day/week/month) handled server-side.

    At least one of instrument_id, symbol, or isin is required.
    from_date and to_date are required query parameters.
    Date range is capped at MARKET_DATA_OHLCV_MAX_DAYS (default 365).
    """
    if instrument_id is None and symbol is None and isin is None:
        raise HTTPException(
            status_code=400,
            detail="At least one of instrument_id, symbol, or isin is required",
        )

    # Enforce date-range cap from settings
    settings = request.app.state.settings
    max_days: int = getattr(settings, "ohlcv_max_days", 365)
    if (to_date - from_date).days > max_days:
        raise HTTPException(
            status_code=422,
            detail=f"Date range exceeds maximum of {max_days} days",
        )

    # Resolve to a canonical instrument via InstrumentLookupUseCase (R25)
    try:
        result = await lookup_uc.execute(
            id=str(instrument_id) if instrument_id else None,
            isin=isin,
            symbol=symbol,
        )
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    instrument = result.instrument
    data = await uc.execute(
        instrument_id=UUID(instrument.id),
        from_date=from_date,
        to_date=to_date,
        interval=interval,
        max_bars=max_bars,
    )

    return OHLCVBarsResponse(
        instrument_id=instrument.id,
        ticker=instrument.symbol,
        interval=interval,
        bars=[OHLCVFlexibleBar(**b) for b in data["bars"]],
        bar_count=data["bar_count"],
    )


@router.get("/ohlcv/bulk", response_model=list[OHLCVListResponse])
async def get_ohlcv_bulk(
    instrument_ids: Annotated[list[str], Query(max_length=200)] = ...,  # type: ignore[assignment]  # F-SEC-007
    timeframe: str = "1d",
    start: date | None = None,
    end: date | None = None,
    uc: Annotated[GetOHLCVBulkUseCase, Depends(get_ohlcv_bulk_uc)] = ...,  # type: ignore[assignment]
) -> list[OHLCVListResponse]:
    """Bulk fetch OHLCV bars for multiple instruments."""
    tf = _resolve_timeframe(timeframe)
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="start must not be after end")

    effective_start = start or date(2000, 1, 1)
    effective_end = end or date(9999, 12, 31)

    all_bars = await uc.execute(instrument_ids, tf, effective_start, effective_end)
    return [
        OHLCVListResponse(
            items=[_to_bar_response(b) for b in bars],
            total=len(bars),
            timeframe=timeframe,
        )
        for bars in all_bars
    ]


@router.get("/ohlcv/{instrument_id}/timeframes", response_model=list[str])
async def get_available_timeframes(
    instrument_id: str,
    uc: Annotated[GetAvailableTimeframesUseCase, Depends(get_available_timeframes_uc)] = ...,  # type: ignore[assignment]
) -> list[str]:
    """Return all timeframes with stored bars for the given instrument."""
    _validate_instrument_id(instrument_id)
    timeframes = await uc.execute(instrument_id)
    return [str(tf) for tf in timeframes]


@router.get("/ohlcv/{instrument_id}/range", response_model=OHLCVRangeResponse)
async def get_ohlcv_range(
    instrument_id: str,
    timeframe: str = "1d",
    uc: Annotated[GetOHLCVRangeUseCase, Depends(get_ohlcv_range_uc)] = ...,  # type: ignore[assignment]
) -> OHLCVRangeResponse:
    """Return the min/max date range for the instrument/timeframe combination."""
    _validate_instrument_id(instrument_id)
    tf = _resolve_timeframe(timeframe)
    result = await uc.execute(instrument_id, tf)
    if result is None:
        return OHLCVRangeResponse(
            instrument_id=instrument_id,
            timeframe=timeframe,
            min_date=None,
            max_date=None,
            count=0,
        )
    min_d, max_d, count = result
    return OHLCVRangeResponse(
        instrument_id=instrument_id,
        timeframe=timeframe,
        min_date=min_d,
        max_date=max_d,
        count=count,
    )


@router.get("/ohlcv/{instrument_id}", response_model=OHLCVListResponse)
async def get_ohlcv_bars(
    instrument_id: str,
    timeframe: str = "1d",
    start: date | None = None,
    end: date | None = None,
    # limit: return only the last N bars (most recent) within the date range.
    # Default 200 covers ~10 months of daily data and is well above any
    # practical chart window. Capped at 1000 to prevent runaway queries.
    limit: int = Query(default=200, ge=1, le=1000),
    uc: Annotated[GetOHLCVBarsUseCase, Depends(get_ohlcv_bars_uc)] = ...,  # type: ignore[assignment]
) -> OHLCVListResponse:
    """Return OHLCV bars for an instrument within an optional date range.

    ``limit`` trims the result to the last N bars (chronologically newest)
    after the date-range filter has been applied.  This is consistent with
    financial chart conventions where callers specify a look-back window
    (e.g. 30 bars for a 30-day chart) rather than a precise date range.
    """
    _validate_instrument_id(instrument_id)
    tf = _resolve_timeframe(timeframe)
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="start must not be after end")

    effective_start = start or date(2000, 1, 1)
    effective_end = end or date(9999, 12, 31)

    bars = await uc.execute(instrument_id, tf, effective_start, effective_end, limit=limit)  # type: ignore[call-arg]
    return OHLCVListResponse(
        items=[_to_bar_response(b) for b in bars],
        total=len(bars),
        timeframe=timeframe,
    )
