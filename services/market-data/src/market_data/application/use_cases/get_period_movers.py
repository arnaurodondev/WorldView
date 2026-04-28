"""Use case: get top period movers (gainers/losers) for the dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork

# Calendar lookback days per period — used against daily bars.
# WHY not derived 1w/1M bars: derived bars require ≥2 such bars per instrument,
# which is rarely available in practice. Daily bars with a calendar lookback work
# with any instrument that has ≥2 trading days of history.
_PERIOD_TO_LOOKBACK_DAYS: dict[str, int] = {
    "1W": 7,
    "1M": 30,
}


class GetPeriodMoversUseCase:
    """Return top gainers or losers by period return from OHLCV bars.

    Uses ReadOnlyUnitOfWork (R27 — query-only use case must not depend on write UoW).
    Only handles 1W and 1M periods. 1D is handled by the existing screener path in S9.
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        period: str,
        mover_type: str = "gainers",
        limit: int = 10,
    ) -> list[dict]:
        """Return [{instrument_id, ticker, name, period_return_pct}] sorted by return.

        mover_type: "gainers" (DESC by period_return_pct) or "losers" (ASC).
        """
        if period not in _PERIOD_TO_LOOKBACK_DAYS:
            msg = f"Unsupported period '{period}' for period movers. Use 1W or 1M."
            raise ValueError(msg)
        if mover_type not in ("gainers", "losers"):
            msg = f"mover_type must be 'gainers' or 'losers', got '{mover_type}'"
            raise ValueError(msg)
        lookback_days = _PERIOD_TO_LOOKBACK_DAYS[period]
        return await self._uow.ohlcv_read.get_period_movers(lookback_days, mover_type, limit)
