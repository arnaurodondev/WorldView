"""Use case: get sector period returns for the dashboard heatmap."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork

# Calendar lookback days per period — used against daily bars.
# WHY not derived 1w/1M bars: see get_period_movers.py for explanation.
# WHY 1D=1: lookback_days is the number of days before the latest bar to find
# the "previous" bar; 1 means "the bar from 1+ day before the latest bar".
_PERIOD_TO_LOOKBACK_DAYS: dict[str, int] = {
    "1D": 1,
    "1W": 7,
    "1M": 30,
}


class GetSectorReturnsUseCase:
    """Return average period return per GICS sector from OHLCV bars.

    Uses ReadOnlyUnitOfWork (R27 — query-only use case must not depend on write UoW).
    Handles 1D, 1W, and 1M periods via the OHLCV bar lookback query.
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, period: str) -> list[dict]:
        """Return [{name, change_pct, instrument_count}] for the given period.

        Raises ValueError for unsupported periods.
        """
        if period not in _PERIOD_TO_LOOKBACK_DAYS:
            msg = f"Unsupported period '{period}' for sector returns. Use 1D, 1W, or 1M."
            raise ValueError(msg)
        lookback_days = _PERIOD_TO_LOOKBACK_DAYS[period]
        return await self._uow.ohlcv_read.get_sector_period_returns(lookback_days)
