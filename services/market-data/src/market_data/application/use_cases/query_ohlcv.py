"""OHLCV query use cases."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork
    from market_data.domain.entities import OHLCVBar
    from market_data.domain.enums import Timeframe


class GetOHLCVBarsUseCase:
    """Return OHLCV bars for an instrument within an optional date range."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        instrument_id: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        *,
        limit: int = 200,
    ) -> list[OHLCVBar]:
        """Fetch the most-recent ``limit`` bars in [start, end].

        WHY limit pushdown: the repository's ``limit`` parameter causes the DB
        to use ``ORDER BY bar_date DESC LIMIT N``, materialising only the rows
        we actually keep.  The previous pattern (fetch all, Python-slice with
        ``[-limit:]``) wasted I/O and Decimal conversion for every bar beyond
        the limit — up to 190 extra rows for a 550-day multi-period-returns
        window.  The repository re-reverses to ASC so callers see no change in
        order semantics.
        """
        return await self._uow.ohlcv_read.find_by_instrument_timeframe_range(
            instrument_id, timeframe, start, end, limit=limit
        )


class GetOHLCVBulkUseCase:
    """Bulk-fetch OHLCV bars for multiple instruments at once."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        instrument_ids: list[str],
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[list[OHLCVBar]]:
        """Return one ``list[OHLCVBar]`` per instrument ID (preserves input order)."""
        repo = self._uow.ohlcv_read
        results = []
        for iid in instrument_ids:
            bars = await repo.find_by_instrument_timeframe_range(iid, timeframe, start, end)
            results.append(bars)
        return results


class GetAvailableTimeframesUseCase:
    """Return all timeframes with stored bars for the given instrument."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, instrument_id: str) -> list[Timeframe]:
        return await self._uow.ohlcv_read.get_available_timeframes(instrument_id)


class GetOHLCVRangeUseCase:
    """Return date range metadata for an instrument/timeframe combination."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        instrument_id: str,
        timeframe: Timeframe,
    ) -> tuple[date, date, int] | None:
        """Return ``(min_date, max_date, bar_count)`` or ``None`` if no data."""
        repo = self._uow.ohlcv_read
        date_range = await repo.get_date_range(instrument_id, timeframe)
        if date_range is None:
            return None
        min_d, max_d = date_range
        all_bars = await repo.find_by_instrument_timeframe_range(
            instrument_id,
            timeframe,
            min_d,
            max_d,
        )
        return min_d, max_d, len(all_bars)
