"""Use case: get top period movers (gainers/losers) for the dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork

_PERIOD_TO_TIMEFRAME: dict[str, str] = {
    "1W": "1w",
    "1M": "1M",
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
        if period not in _PERIOD_TO_TIMEFRAME:
            msg = f"Unsupported period '{period}' for period movers. Use 1W or 1M."
            raise ValueError(msg)
        if mover_type not in ("gainers", "losers"):
            msg = f"mover_type must be 'gainers' or 'losers', got '{mover_type}'"
            raise ValueError(msg)
        timeframe = _PERIOD_TO_TIMEFRAME[period]
        return await self._uow.ohlcv_read.get_period_movers(timeframe, mover_type, limit)
