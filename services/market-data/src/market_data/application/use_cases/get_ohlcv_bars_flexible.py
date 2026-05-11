"""GetOHLCVBarsFlexibleUseCase — flexible OHLCV bars with interval resampling (PLAN-0066 Wave G).

Differs from GetOHLCVBarsUseCase (which takes a Timeframe enum and an instrument_id string)
by accepting a date range + interval string (day/week/month) and returning a flat dict
representation suitable for the temporal RAG endpoints.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork


class GetOHLCVBarsFlexibleUseCase:
    """Return OHLCV bars for an instrument within a date range with optional resampling.

    WHY a separate use case: the existing GetOHLCVBarsUseCase is coupled to the
    Timeframe enum and returns domain OHLCVBar objects.  This use case:
    - accepts interval strings ("day"/"week"/"month") from the temporal RAG API
    - maps them to the 1d/1w/1M Timeframe values already stored in the DB
    - returns plain dicts for serialisation (no Decimal/datetime objects)
    - truncates to max_bars (tail-slice: newest first)
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        instrument_id: UUID,
        from_date: date,
        to_date: date,
        interval: str = "day",
        max_bars: int = 252,
    ) -> dict:
        """Return bars in {"bars": [...], "bar_count": int}.

        ``interval`` maps to existing Timeframe values:
          "day"   → Timeframe.ONE_DAY  ("1d")
          "week"  → Timeframe.ONE_WEEK ("1w")
          "month" → Timeframe.ONE_MONTH ("1M")

        Bars are ordered ASC by date; max_bars is applied as a tail-slice
        (most-recent N bars) consistent with financial chart conventions.
        """
        from market_data.domain.enums import Timeframe

        _interval_map = {
            "day": Timeframe.ONE_DAY,
            "week": Timeframe.ONE_WEEK,
            "month": Timeframe.ONE_MONTH,
        }
        timeframe = _interval_map.get(interval, Timeframe.ONE_DAY)
        iid_str = str(instrument_id)

        bars = await self._uow.ohlcv_read.find_by_instrument_timeframe_range(
            iid_str,
            timeframe,
            from_date,
            to_date,
        )

        # Tail-slice: newest N bars
        if len(bars) > max_bars:
            bars = bars[-max_bars:]

        result = [
            {
                "date": b.bar_date.strftime("%Y-%m-%d"),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": int(b.volume) if b.volume is not None else 0,
            }
            for b in bars
        ]

        return {"bars": result, "bar_count": len(result)}
