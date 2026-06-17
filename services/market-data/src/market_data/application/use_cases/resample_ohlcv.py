"""ResampledOHLCVUseCase — derive coarser bars from a finest-granularity source bar.

When a new bar at the configured source timeframe is persisted, this use case
resamples it into all coarser intraday timeframes including 1d.  For each target
timeframe it:

1. Floors the trigger bar's timestamp to the period boundary.
2. Fetches all source-TF bars in [period_start, trigger_bar.bar_date].
3. Aggregates them into a single derived bar.
4. Marks the bar as ``is_partial=True`` when the trigger bar is earlier than
   the period end (the canonical "open bar" semantics).

The source timeframe is configurable (default: 1m) so that the pipeline can be
migrated to 5m or 15m as the finest available granularity purely by changing the
``MARKET_DATA_INTRADAY_SOURCE_TF`` env var — no code change required (BP-254).

Derived bars are upserted via ``bulk_upsert_derived`` so each new source tick
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

# Maps every timeframe (source AND target) to its period length in seconds.
# ONE_DAY uses calendar-day (UTC midnight) boundaries — works correctly for
# US markets where all NYSE/NASDAQ trading falls within a single UTC day.
_PERIOD_SECONDS: dict[Timeframe, int] = {
    Timeframe.ONE_MIN: 60,
    Timeframe.FIVE_MIN: 300,
    Timeframe.FIFTEEN_MIN: 900,
    Timeframe.THIRTY_MIN: 1800,
    Timeframe.ONE_HOUR: 3600,
    Timeframe.FOUR_HOUR: 14400,
    Timeframe.ONE_DAY: 86400,
}

# Source tag stored on all derived bars.
_DERIVED_SOURCE = "derived"

# Derived bars are the AUTHORITATIVE source for every timeframe they cover
# (they are aggregated from Alpaca 1m — the single source of truth).  They are
# written via the unconditional ``bulk_upsert_derived`` path, so they already
# overwrite any competing row regardless of priority; we nonetheless tag them
# with the top-of-ladder ``derived`` priority (see ``_PROVIDER_PRIORITIES``) so
# that the ASYMMETRIC case also resolves correctly: a later POLLED daily bar
# arriving via the priority-guarded ``bulk_upsert_with_priority`` (EODHD=60,
# Yahoo=80) can NO LONGER clobber a derived bar, because its priority is below
# ``derived``.  This kills the eodhd<->derived flip-flop on liquid symbols.
_DERIVED_PRIORITY = ProviderPriority(provider="derived", priority=110)

# Default targets when the caller does not specify a subset.
# Only timeframes strictly coarser than the source are actually derived
# (filtering happens dynamically in execute() based on source_timeframe).
_DEFAULT_TARGET_TIMEFRAMES: list[Timeframe] = [
    Timeframe.FIVE_MIN,
    Timeframe.FIFTEEN_MIN,
    Timeframe.THIRTY_MIN,
    Timeframe.ONE_HOUR,
    Timeframe.FOUR_HOUR,
    Timeframe.ONE_DAY,
]


def _floor_to_period(bar_dt: datetime, period_seconds: int) -> datetime:
    """Floor a UTC datetime to the nearest period boundary.

    Example: _floor_to_period(09:13, 300) -> 09:10:00 UTC.
    Works for any period including 86400 (daily, floored to UTC midnight).
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
    """Aggregate a list of source bars into a single derived bar.

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
    """Derive coarser bars from a finest-granularity source bar.

    Parameters
    ----------
    uow:
        Write-capable unit of work.
    source_timeframe:
        The timeframe of the incoming trigger bar (default: ONE_MIN).
        Driven by ``MARKET_DATA_INTRADAY_SOURCE_TF`` env var so that switching
        from 1m to 5m requires only a config change (BP-254).
    """

    def __init__(
        self,
        uow: UnitOfWork,
        source_timeframe: Timeframe = Timeframe.ONE_MIN,
    ) -> None:
        self._uow = uow
        self._source_tf = source_timeframe

    async def execute(
        self,
        bar: OHLCVBar,
        target_timeframes: list[Timeframe] | None = None,
    ) -> list[OHLCVBar]:
        """Resample the trigger ``bar`` into each target timeframe.

        Parameters
        ----------
        bar:
            The source-timeframe trigger bar that was just persisted.
        target_timeframes:
            Subset of timeframes to derive.  Defaults to all configured targets.
            Only timeframes strictly coarser than the source are processed.

        Returns
        -------
        list[OHLCVBar]
            The derived bars that were upserted.
        """
        if target_timeframes is None:
            target_timeframes = _DEFAULT_TARGET_TIMEFRAMES

        # Only derive timeframes strictly coarser than the source so that
        # e.g. with source=5m we skip 5m itself and derive 15m/30m/1h/4h/1d.
        source_seconds = _PERIOD_SECONDS.get(self._source_tf, 60)
        effective_targets = [tf for tf in target_timeframes if _PERIOD_SECONDS.get(tf, 0) > source_seconds]

        derived_bars: list[OHLCVBar] = []

        for target_tf in effective_targets:
            period_sec = _PERIOD_SECONDS[target_tf]
            period_start = _floor_to_period(bar.bar_date, period_sec)
            period_end = period_start + timedelta(seconds=period_sec)

            # Fetch all source-TF bars in [period_start, bar.bar_date] so the
            # aggregate reflects everything stored so far for this period.
            source_bars = await self._uow.ohlcv.find_by_instrument_timeframe_datetime_range(
                instrument_id=bar.instrument_id,
                timeframe=self._source_tf,
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
                source_timeframe=str(self._source_tf),
                derived_count=len(derived_bars),
                is_partial_count=sum(1 for b in derived_bars if b.is_partial),
            )

        return derived_bars
