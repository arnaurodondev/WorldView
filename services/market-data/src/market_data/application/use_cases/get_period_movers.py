"""Use case: get top period movers (gainers/losers) for the dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork

# Calendar lookback days per period — used against daily bars.
# WHY not derived 1w/1M bars: derived bars require ≥2 such bars per instrument,
# which is rarely available in practice. Daily bars with a calendar lookback work
# with any instrument that has ≥2 trading days of history.
# WHY 1D included: fundamental_metrics.daily_return is only populated for ~8 instruments;
# the OHLCV LATERAL JOIN yields 500+ instruments with real day-over-day returns.
_PERIOD_TO_LOOKBACK_DAYS: dict[str, int] = {
    "1D": 1,
    "1W": 7,
    "1M": 30,
}


class GetPeriodMoversUseCase:
    """Return top gainers or losers by period return from OHLCV bars.

    Uses ReadOnlyUnitOfWork (R27 — query-only use case must not depend on write UoW).
    Handles 1D, 1W, and 1M periods — all use the OHLCV LATERAL JOIN path.
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        period: str,
        mover_type: str = "gainers",
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict]:
        """Return [{instrument_id, ticker, name, period_return_pct}] sorted by return.

        mover_type: "gainers" (DESC by period_return_pct) or "losers" (ASC).
        offset: pagination offset into the sorted universe (forwarded to SQL OFFSET).
        """
        if period not in _PERIOD_TO_LOOKBACK_DAYS:
            msg = f"Unsupported period '{period}' for period movers. Use 1W or 1M."
            raise ValueError(msg)
        if mover_type not in ("gainers", "losers"):
            msg = f"mover_type must be 'gainers' or 'losers', got '{mover_type}'"
            raise ValueError(msg)
        if offset < 0:
            msg = f"offset must be >= 0, got {offset}"
            raise ValueError(msg)
        lookback_days = _PERIOD_TO_LOOKBACK_DAYS[period]
        return await self._uow.ohlcv_read.get_period_movers(lookback_days, mover_type, limit, offset)
