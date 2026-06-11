"""Quote-tab statistics router (B-Q-2 / B-Q-3 / B-Q-4).

Exposes:
  GET /api/v1/instruments/{instrument_id}/intraday-stats
  GET /api/v1/instruments/{instrument_id}/returns
  GET /api/v1/instruments/{instrument_id}/price-levels

WHY a separate router: these three endpoints share one concern (per-instrument
statistics computed from daily/intraday OHLCV bars) and one dependency set
(the query_quote_stats use cases). Keeping them out of ohlcv.py / instruments.py
avoids bloating those routers, mirroring the peers.py precedent.

R25/R16: routes call only use cases (no infrastructure imports).
R27: all three use cases receive a ReadOnlyUnitOfWork via get_read_uow.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from market_data.api.dependencies import (
    get_intraday_stats_uc,
    get_multi_period_returns_uc,
    get_price_levels_uc,
)
from market_data.api.schemas.quote_stats import (
    IntradayStatsResponse,
    MultiPeriodReturnsResponse,
    PriceLevelsResponse,
)
from market_data.application.use_cases.query_quote_stats import (
    GetIntradayStatsUseCase,
    GetMultiPeriodReturnsUseCase,
    GetPriceLevelsUseCase,
)
from market_data.domain.errors import InstrumentNotFoundError

router = APIRouter(tags=["quote-stats"])


def _validate_uuid(instrument_id: str) -> str:
    """Reject non-UUID path params with 422 (prevents asyncpg DataError → 500)."""
    try:
        UUID(instrument_id)
    except (ValueError, AttributeError):
        raise HTTPException(  # noqa: B904
            status_code=422,
            detail=f"Invalid instrument_id format: '{instrument_id}' — must be a UUID",
        )
    return instrument_id


@router.get("/instruments/{instrument_id}/intraday-stats", response_model=IntradayStatsResponse)
async def get_intraday_stats(
    instrument_id: str,
    uc: Annotated[GetIntradayStatsUseCase, Depends(get_intraday_stats_uc)],
) -> IntradayStatsResponse:
    """Return current-session stats: open, prev close, H/L, VWAP, volume + 30d ratio.

    404 when the instrument does not exist; all-null payload (200) when it
    exists but has no OHLCV bars yet — the frontend renders "—" cells.
    """
    _validate_uuid(instrument_id)
    try:
        result = await uc.execute(instrument_id)
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return IntradayStatsResponse(**result)


@router.get("/instruments/{instrument_id}/returns", response_model=MultiPeriodReturnsResponse)
async def get_multi_period_returns(
    instrument_id: str,
    uc: Annotated[GetMultiPeriodReturnsUseCase, Depends(get_multi_period_returns_uc)],
) -> MultiPeriodReturnsResponse:
    """Return 1D/1W/1M/3M/6M/YTD/1Y/3Y/5Y % returns from daily closes.

    Periods with insufficient history are null — never extrapolated.
    """
    _validate_uuid(instrument_id)
    try:
        result = await uc.execute(instrument_id)
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MultiPeriodReturnsResponse(**result)


@router.get("/instruments/{instrument_id}/price-levels", response_model=PriceLevelsResponse)
async def get_price_levels(
    instrument_id: str,
    uc: Annotated[GetPriceLevelsUseCase, Depends(get_price_levels_uc)],
) -> PriceLevelsResponse:
    """Return 52w range + distances, MA50/MA200, prior-session H/L and swing S/R.

    The support/resistance derivation is described in the response's
    ``sr_method`` field (fractal swing points — simple and documented).
    """
    _validate_uuid(instrument_id)
    try:
        result = await uc.execute(instrument_id)
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PriceLevelsResponse(**result)
