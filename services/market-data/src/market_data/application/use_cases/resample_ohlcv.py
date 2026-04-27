"""ResampledOHLCVUseCase -- derive intraday bars from 1m bars with open-bar semantics.

When a new 1-minute bar is persisted, this use case resamples it into coarser
intraday timeframes (5m, 15m, 30m, 1h, 4h).  For each target timeframe it:

1. Floors the trigger bar's timestamp to the period boundary.
2. Fetches all 1m bars in [period_start, trigger_bar.bar_date].
3. Aggregates them into a single derived bar.
4. Marks the bar as ``is_partial=True`` when the trigger bar is earlier than
   the period end (the canonical "open bar" semantics).

Derived bars are upserted via ``bulk_upsert_derived`` so each new 1m tick
continuously refines the open bar until the period closes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_data.application.ports.uow import UnitOfWork

logger = get_logger(__name__)

# Maps each target timeframe to its period length in seconds.
_PERIOD_SECONDS: dict[Timeframe, int] = {
    Timeframe.FIVE_MIN: 300,
    Timeframe.FIFTEEN_MIN: 900,
    Timeframe.THIRTY_MIN: 1800,
    Timeframe.ONE_HOUR: 3600,
    Timeframe.FOUR_HOUR: 14400,
}

# Source tag stored on all derived bars.
_DERIVED_SOURCE = "derived"

# Derived bars carry priority=0 -- they are never involved in provider-priority
# conflict resolution (they go through ``bulk_upsert_derived``, not the
# priority-guarded path).
_DERIVED_PRIORITY = ProviderPriority(provider="unknown", priority=0)

# Default targets when the caller does not specify a subset.
_DEFAULT_TARGET_TIMEFRAMES: list[Timeframe] = [
    Timeframe.FIVE_MIN,
    Timeframe.FIFTEEN_MIN,
    Timeframe.THIRTY_MIN,
    Timeframe.ONE_HOUR,
    Timeframe.FOUR_HOUR,
]


def _floor_to_period(bar_dt: datetime, period_seconds: int) -> datetime:
    """Floor a UTC datetime to the nearest period boundary.

    Example: _floor_to_period(09:13, 300) -> 09:10:00 UTC.
    """
    epoch_seconds = int(bar_dt.timestamp())
    period_start_epoch = (epoch_seconds // period_seconds) * period_seconds
    return datetime.fromtimestamp(period_start_epoch, tz=UTC)


def _aggregate_bars(
    instrument_id: str,
    target_tf: Timeframe,
    period_start: datetime,
    period_end: datetime,
    source_bars: list[OHLCVBar],
    trigger_bar: OHLCVBar,
) -> OHLCVBar:
    """Aggregate a list of 1m source bars into a single derived bar.

    OHLCV semantics:
    - open  = first bar's open
    - high  = max(high) across all bars
    - low   = min(low) across all bars
    - close = last bar's close
    - volume = sum(volume)

    The bar is marked partial when the trigger bar's timestamp is strictly
    before the period end (i.e. the period has not closed yet).
    """
    first = source_bars[0]
    last = source_bars[-1]
    is_partial = trigger_bar.bar_date < period_end

    return OHLCVBar(
        instrument_id=instrument_id,
        timeframe=target_tf,
        bar_date=period_start,
        open=first.open,
        high=max(b.high for b in source_bars),
        low=min(b.low for b in source_bars),
        close=last.close,
        volume=sum((b.volume or 0) for b in source_bars),
        adjusted_close=None,
        source=_DERIVED_SOURCE,
        provider_priority=_DERIVED_PRIORITY,
        is_derived=True,
        is_partial=is_partial,
    )


class ResampledOHLCVUseCase:
    """Derive intraday bars (5m/15m/30m/1h/4h) from a single 1m trigger bar."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        bar: OHLCVBar,
        target_timeframes: list[Timeframe] | None = None,
    ) -> list[OHLCVBar]:
        """Resample the trigger ``bar`` into each target timeframe.

        Parameters
        ----------
        bar:
            The 1-minute trigger bar that was just persisted.
        target_timeframes:
            Subset of timeframes to derive.  Defaults to all five intraday
            timeframes (5m, 15m, 30m, 1h, 4h).

        Returns
        -------
        list[OHLCVBar]
            The derived bars that were upserted.
        """
        if target_timeframes is None:
            target_timeframes = _DEFAULT_TARGET_TIMEFRAMES

        derived_bars: list[OHLCVBar] = []

        for target_tf in target_timeframes:
            period_sec = _PERIOD_SECONDS[target_tf]
            period_start = _floor_to_period(bar.bar_date, period_sec)
            period_end = period_start + timedelta(seconds=period_sec)

            # Fetch all 1m bars in [period_start, bar.bar_date] so the
            # aggregate reflects everything stored so far for this period.
            source_bars = await self._uow.ohlcv.find_by_instrument_timeframe_datetime_range(
                instrument_id=bar.instrument_id,
                timeframe=Timeframe.ONE_MIN,
                start_dt=period_start,
                end_dt=bar.bar_date,
            )

            # Fall back to the trigger bar itself when the DB query returns
            # nothing (e.g. bar not yet committed, or first bar in period).
            if not source_bars:
                source_bars = [bar]

            derived = _aggregate_bars(
                instrument_id=bar.instrument_id,
                target_tf=target_tf,
                period_start=period_start,
                period_end=period_end,
                source_bars=source_bars,
                trigger_bar=bar,
            )
            derived_bars.append(derived)

        if derived_bars:
            await self._uow.ohlcv.bulk_upsert_derived(derived_bars)
            logger.debug(
                "intraday_resampling_bar_processed",
                instrument_id=bar.instrument_id,
                source_timeframe="1m",
                derived_count=len(derived_bars),
                is_partial_count=sum(1 for b in derived_bars if b.is_partial),
            )

        return derived_bars
