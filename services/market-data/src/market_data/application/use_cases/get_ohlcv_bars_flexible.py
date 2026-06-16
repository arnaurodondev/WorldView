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


# Weekly/monthly intervals are DERIVED on the fly from stored daily bars
# (PLAN-0036 intent: no provider polling, no storage growth).  These are the
# interval spellings that trigger query-time derivation in this use case.
_WEEK_INTERVALS = frozenset({"week", "1w"})
_MONTH_INTERVALS = frozenset({"month", "1mo", "1M"})


class GetOHLCVBarsFlexibleUseCase:
    """Return OHLCV bars for an instrument within a date range with optional resampling.

    WHY a separate use case: the existing GetOHLCVBarsUseCase is coupled to the
    Timeframe enum and returns domain OHLCVBar objects.  This use case:
    - accepts interval strings ("day"/"week"/"month") from the temporal RAG API
    - maps them to the 1d/1w/1M Timeframe values already stored in the DB
    - DERIVES weekly/monthly bars on the fly from stored daily bars (query-time
      aggregation — no storage growth, no write-on-read, R27-safe)
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
          "1m"/"5m"/"15m"/"30m"/"1h"/"4h" → intraday Timeframes (PLAN-0109 B-3:
              needed so the rag-chat get_price_history tool can serve
              "what is X trading at?" via the most recent 1-minute bar)
          "day"   → Timeframe.ONE_DAY  ("1d")
          "week"  → Timeframe.ONE_WEEK ("1w")
          "month" → Timeframe.ONE_MONTH ("1M")

        Weekly (``week``/``1w``) and monthly (``month``/``1mo``/``1M``) intervals
        are DERIVED on the fly from the stored daily (``1d``) bars in the
        requested range — no provider polling, no storage growth, no write on
        the read path (R27-safe).  All other intervals are a plain table read.

        Bars are ordered ASC by date; max_bars is applied as a tail-slice
        (most-recent N bars) consistent with financial chart conventions.
        """
        from market_data.domain.enums import Timeframe

        iid_str = str(instrument_id)

        # ── Derived path: weekly / monthly aggregated from daily ──────────────
        if interval in _WEEK_INTERVALS or interval in _MONTH_INTERVALS:
            target = Timeframe.ONE_WEEK if interval in _WEEK_INTERVALS else Timeframe.ONE_MONTH
            derived = await self._derive_from_daily(iid_str, from_date, to_date, target)
            # Tail-slice: newest N derived bars
            if len(derived) > max_bars:
                derived = derived[-max_bars:]
            return {"bars": derived, "bar_count": len(derived)}

        # ── Direct path: intraday + daily are stored directly ────────────────
        _interval_map = {
            "1m": Timeframe.ONE_MIN,
            "5m": Timeframe.FIVE_MIN,
            "15m": Timeframe.FIFTEEN_MIN,
            "30m": Timeframe.THIRTY_MIN,
            "1h": Timeframe.ONE_HOUR,
            "4h": Timeframe.FOUR_HOUR,
            "day": Timeframe.ONE_DAY,
            "1d": Timeframe.ONE_DAY,
        }
        timeframe = _interval_map.get(interval, Timeframe.ONE_DAY)

        bars = await self._uow.ohlcv_read.find_by_instrument_timeframe_range(
            iid_str,
            timeframe,
            from_date,
            to_date,
        )

        # Tail-slice: newest N bars
        if len(bars) > max_bars:
            bars = bars[-max_bars:]

        # Intraday bars share a calendar date — keep the time component so
        # consumers (and the rag-chat price tool) can distinguish bars and
        # identify the most-recent one. Daily+ keeps the original date-only
        # shape for backward compatibility with existing consumers.
        intraday = interval in ("1m", "5m", "15m", "30m", "1h", "4h")
        date_fmt = "%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d"

        result = [
            {
                "date": b.bar_date.strftime(date_fmt),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": int(b.volume) if b.volume is not None else 0,
            }
            for b in bars
        ]

        return {"bars": result, "bar_count": len(result)}

    async def _derive_from_daily(
        self,
        instrument_id: str,
        from_date: date,
        to_date: date,
        target: object,  # Timeframe.ONE_WEEK | Timeframe.ONE_MONTH
    ) -> list[dict]:
        """Aggregate stored daily bars into weekly/monthly bars in-memory.

        Uses the shared ``derive_bars_in_memory`` helper so this flexible
        endpoint and the PATH endpoint (``GetOHLCVBarsUseCase``) derive
        weekly/monthly bars identically (ISO-week Monday anchor / calendar-month
        day-1 anchor; open=first, high=max, low=min, close=last, volume=sum).
        Does NOT persist — read-only request path (R27).
        """
        from market_data.application.use_cases.derive_ohlcv import derive_bars_in_memory
        from market_data.domain.enums import Timeframe

        tgt = target if isinstance(target, Timeframe) else Timeframe(str(target))

        daily = await self._uow.ohlcv_read.find_by_instrument_timeframe_range(
            instrument_id,
            Timeframe.ONE_DAY,
            from_date,
            to_date,
        )
        derived_bars = derive_bars_in_memory(instrument_id, tgt, daily)

        return [
            {
                "date": b.bar_date.strftime("%Y-%m-%d"),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": int(b.volume) if b.volume is not None else 0,
            }
            for b in derived_bars
        ]
