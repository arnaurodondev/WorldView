"""OHLCV API router."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from market_data.api.dependencies import (
    get_available_timeframes_uc,
    get_ohlcv_bars_uc,
    get_ohlcv_bulk_uc,
    get_ohlcv_range_uc,
)
from market_data.api.schemas.ohlcv import OHLCVBarResponse, OHLCVListResponse, OHLCVRangeResponse
from market_data.application.use_cases.query_ohlcv import (
    GetAvailableTimeframesUseCase,
    GetOHLCVBarsUseCase,
    GetOHLCVBulkUseCase,
    GetOHLCVRangeUseCase,
)
from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe

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
        volume=bar.volume,
        adjusted_close=str(bar.adjusted_close) if bar.adjusted_close is not None else None,
        source=bar.source,
    )


def _resolve_timeframe(timeframe_str: str) -> Timeframe:
    try:
        return Timeframe(timeframe_str)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid timeframe: {timeframe_str}")  # noqa: B904


# IMPORTANT: literal-path routes must come BEFORE {instrument_id} route
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
    timeframes = await uc.execute(instrument_id)
    return [str(tf) for tf in timeframes]


@router.get("/ohlcv/{instrument_id}/range", response_model=OHLCVRangeResponse)
async def get_ohlcv_range(
    instrument_id: str,
    timeframe: str = "1d",
    uc: Annotated[GetOHLCVRangeUseCase, Depends(get_ohlcv_range_uc)] = ...,  # type: ignore[assignment]
) -> OHLCVRangeResponse:
    """Return the min/max date range for the instrument/timeframe combination."""
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
    uc: Annotated[GetOHLCVBarsUseCase, Depends(get_ohlcv_bars_uc)] = ...,  # type: ignore[assignment]
) -> OHLCVListResponse:
    """Return OHLCV bars for an instrument within an optional date range."""
    tf = _resolve_timeframe(timeframe)
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="start must not be after end")

    effective_start = start or date(2000, 1, 1)
    effective_end = end or date(9999, 12, 31)

    bars = await uc.execute(instrument_id, tf, effective_start, effective_end)
    return OHLCVListResponse(
        items=[_to_bar_response(b) for b in bars],
        total=len(bars),
        timeframe=timeframe,
    )
