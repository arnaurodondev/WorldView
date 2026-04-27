"""Use case: get sector period returns for the dashboard heatmap."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork

# Maps frontend period strings to OHLCV timeframe column values in the DB.
# "1D" is not handled here — for daily returns the caller falls back to the
# screener approach (see S9 clients.py). "1w" and "1M" match the timeframe
# values stored in ohlcv_bars by the OHLCV consumer.
_PERIOD_TO_TIMEFRAME: dict[str, str] = {
    "1W": "1w",
    "1M": "1M",
}


class GetSectorReturnsUseCase:
    """Return average period return per GICS sector from OHLCV bars.

    Uses ReadOnlyUnitOfWork (R27 — query-only use case must not depend on write UoW).
    Only handles 1W and 1M periods. 1D is delegated to the screener-based path in S9.
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, period: str) -> list[dict]:
        """Return [{name, change_pct, instrument_count}] for the given period.

        Raises ValueError for unsupported periods (1D must be routed elsewhere).
        """
        if period not in _PERIOD_TO_TIMEFRAME:
            msg = f"Unsupported period '{period}' for sector returns. Use 1W or 1M."
            raise ValueError(msg)
        timeframe = _PERIOD_TO_TIMEFRAME[period]
        return await self._uow.ohlcv_read.get_sector_period_returns(timeframe)
