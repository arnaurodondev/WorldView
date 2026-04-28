"""Use case: get sector period returns for the dashboard heatmap."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork

# Calendar lookback days per period — used against daily bars.
# WHY not derived 1w/1M bars: see get_period_movers.py for explanation.
_PERIOD_TO_LOOKBACK_DAYS: dict[str, int] = {
    "1W": 7,
    "1M": 30,
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
        if period not in _PERIOD_TO_LOOKBACK_DAYS:
            msg = f"Unsupported period '{period}' for sector returns. Use 1W or 1M."
            raise ValueError(msg)
        lookback_days = _PERIOD_TO_LOOKBACK_DAYS[period]
        return await self._uow.ohlcv_read.get_sector_period_returns(lookback_days)
