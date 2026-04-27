"""Market aggregation router — period-based sector returns and top movers.

WHY SEPARATE ROUTER: These endpoints are composite aggregations across multiple
instruments/sectors, not CRUD for a single entity. Keeping them separate from
ohlcv.py (which is per-instrument) and fundamentals.py prevents those routers
from growing unwieldy.

Both endpoints use ReadUoWDep (R27) since they are read-only aggregations.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from market_data.api.dependencies import get_period_movers_uc, get_sector_returns_uc
from market_data.application.use_cases.get_period_movers import GetPeriodMoversUseCase
from market_data.application.use_cases.get_sector_returns import GetSectorReturnsUseCase

router = APIRouter(tags=["market"])


@router.get("/market/sector-returns")
async def sector_returns(
    period: Annotated[str, Query(description="Period: 1W or 1M")] = "1W",
    uc: GetSectorReturnsUseCase = Depends(get_sector_returns_uc),
) -> dict:
    """Sector heatmap data aggregated from OHLCV bars for weekly/monthly periods.

    Returns average period return per GICS sector.
    Use S9 /v1/market/heatmap?period=1D for daily (screener-based).
    """
    if period not in ("1W", "1M"):
        raise HTTPException(status_code=400, detail="period must be '1W' or '1M'")
    try:
        sectors = await uc.execute(period)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"sectors": sectors}


@router.get("/market/period-movers")
async def period_movers(
    period: Annotated[str, Query(description="Period: 1W or 1M")] = "1W",
    mover_type: Annotated[str, Query(alias="type", description="gainers or losers")] = "gainers",
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    uc: GetPeriodMoversUseCase = Depends(get_period_movers_uc),
) -> dict:
    """Top gainers or losers by period return computed from OHLCV bars.

    Returns list of instruments sorted by their period_return_pct.
    """
    if period not in ("1W", "1M"):
        raise HTTPException(status_code=400, detail="period must be '1W' or '1M'")
    if mover_type not in ("gainers", "losers"):
        raise HTTPException(status_code=400, detail="type must be 'gainers' or 'losers'")
    try:
        results = await uc.execute(period, mover_type, limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"results": results, "type": mover_type, "period": period}
