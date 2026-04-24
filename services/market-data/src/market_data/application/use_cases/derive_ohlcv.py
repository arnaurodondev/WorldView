"""DeriveOHLCVUseCase — aggregate daily bars into weekly or monthly derived bars.

This use case eliminates EODHD API credit consumption for the 1W and 1M
timeframes (PLAN-0036 W2-4).  Instead of polling EODHD's ``/eod/1W`` and
``/eod/1M`` endpoints, we aggregate the already-stored daily (``1d``) bars
locally and persist the result with ``is_derived=True``.

Aggregation rules
-----------------
Weekly (Timeframe.ONE_WEEK):
  * Group daily bars by ISO week number (Monday = start of week).
  * ``bar_date`` = Monday of that ISO week (UTC midnight).
  * open  = first calendar day's open in the week.
  * high  = max(high) across all days in the week.
  * low   = min(low)  across all days in the week.
  * close = last calendar day's close in the week.
  * volume = sum(volume) across all days.

Monthly (Timeframe.ONE_MONTH):
  * Group daily bars by (year, month).
  * ``bar_date`` = first day of that month (UTC midnight).
  * Same OHLCV aggregation logic as weekly.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_data.application.ports.uow import UnitOfWork

logger = get_logger(__name__)

# The derivation source (provider tag stored in the ``source`` column of derived bars).
_DERIVED_SOURCE = "derived"

# Derived bars carry priority=0 — they are never used in the provider-priority
# conflict-resolution path (bulk_upsert_with_priority).  They are always
# upserted via bulk_upsert_derived which has no priority guard.
_DERIVED_PRIORITY = ProviderPriority(provider="unknown", priority=0)

# Timeframes that can be derived from daily bars.
_DERIVABLE: frozenset[Timeframe] = frozenset({Timeframe.ONE_WEEK, Timeframe.ONE_MONTH})


def _iso_week_monday(d: date) -> date:
    """Return the Monday of the ISO week that contains ``d``."""
    # weekday() returns 0 for Monday, 6 for Sunday.
    return d - timedelta(days=d.weekday())


def _month_first(d: date) -> date:
    """Return the first day of the month that contains ``d``."""
    return d.replace(day=1)


def _group_key(bar_date: date, target_timeframe: Timeframe) -> date:
    """Return the canonical ``bar_date`` for the target timeframe bucket."""
    if target_timeframe == Timeframe.ONE_WEEK:
        return _iso_week_monday(bar_date)
    # ONE_MONTH
    return _month_first(bar_date)


def _aggregate_group(instrument_id: str, timeframe: Timeframe, bucket: date, bars: list[OHLCVBar]) -> OHLCVBar:
    """Aggregate a list of daily bars into one derived bar for ``bucket``.

    ``bars`` must be sorted ascending by ``bar_date`` before this call.
    """
    # open = first day's open; close = last day's close.
    first = bars[0]
    last = bars[-1]
    high = max(b.high for b in bars)
    low = min(b.low for b in bars)
    volume = sum(b.volume or 0 for b in bars)

    return OHLCVBar(
        instrument_id=instrument_id,
        timeframe=timeframe,
        # bar_date is stored as UTC-midnight datetime to match the existing
        # convention in ohlcv_bars (all bar_dates are date-level timestamps).
        bar_date=datetime(bucket.year, bucket.month, bucket.day, tzinfo=UTC),
        open=first.open,
        high=high,
        low=low,
        close=last.close,
        volume=volume,
        adjusted_close=None,  # No adjusted_close for derived bars.
        source=_DERIVED_SOURCE,
        provider_priority=_DERIVED_PRIORITY,
        is_derived=True,
    )


class DeriveOHLCVUseCase:
    """Aggregate daily OHLCV bars into weekly or monthly derived bars.

    Accepts a symbol/exchange pair, resolves the instrument, loads all stored
    daily bars, aggregates them, and upserts the derived bars back into the
    repository.

    Returns the count of derived bars written.

    Usage::

        async with uow_factory() as uow:
            uc = DeriveOHLCVUseCase(uow)
            count = await uc.execute(
                symbol="AAPL",
                exchange="US",
                target_timeframe=Timeframe.ONE_WEEK,
            )
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        symbol: str,
        exchange: str,
        *,
        source_timeframe: str = "1d",
        target_timeframe: str,
    ) -> int:
        """Derive bars for ``target_timeframe`` from ``source_timeframe`` bars.

        Parameters
        ----------
        symbol:
            Instrument ticker symbol (e.g. ``"AAPL"``).
        exchange:
            Exchange code (e.g. ``"US"``).
        source_timeframe:
            Timeframe of the source bars.  Must be ``"1d"`` (daily).
        target_timeframe:
            Timeframe to derive.  Must be ``"1w"`` (weekly) or ``"1M"`` (monthly).

        Returns
        -------
        int
            Number of derived bars written to the repository.
        """
        # ── 1. Validate target timeframe ──────────────────────────────────────
        try:
            src_tf = Timeframe(source_timeframe)
            tgt_tf = Timeframe(target_timeframe)
        except ValueError as exc:
            raise ValueError(f"Unknown timeframe: {exc}") from exc

        if tgt_tf not in _DERIVABLE:
            raise ValueError(
                f"target_timeframe must be one of {[t.value for t in _DERIVABLE]}, got {target_timeframe!r}"
            )

        log = logger.bind(symbol=symbol, exchange=exchange, source_tf=src_tf, target_tf=tgt_tf)

        # ── 2. Resolve instrument ─────────────────────────────────────────────
        instrument = await self._uow.instruments_read.find_by_symbol_exchange(symbol, exchange)
        if instrument is None:
            log.warning("derive_ohlcv.instrument_not_found")
            return 0

        instrument_id = instrument.id

        # ── 3. Load source (daily) bars ───────────────────────────────────────
        date_range = await self._uow.ohlcv_read.get_date_range(instrument_id, src_tf)
        if date_range is None:
            log.info("derive_ohlcv.no_source_bars")
            return 0

        start_date, end_date = date_range
        source_bars = await self._uow.ohlcv_read.find_by_instrument_timeframe_range(
            instrument_id,
            src_tf,
            start_date,
            end_date,
        )

        if not source_bars:
            log.info("derive_ohlcv.no_source_bars_after_fetch")
            return 0

        log.info("derive_ohlcv.source_bars_loaded", count=len(source_bars))

        # ── 4. Bucket bars by target timeframe ────────────────────────────────
        # Use an ordered dict keyed by the canonical bar_date for the bucket
        # so that within each group the bars remain in ascending date order.
        buckets: dict[date, list[OHLCVBar]] = defaultdict(list)
        for bar in sorted(source_bars, key=lambda b: b.bar_date):
            key = _group_key(bar.bar_date.date(), tgt_tf)
            buckets[key].append(bar)

        # ── 5. Aggregate each bucket ──────────────────────────────────────────
        derived_bars: list[OHLCVBar] = [
            _aggregate_group(instrument_id, tgt_tf, bucket_date, group_bars)
            for bucket_date, group_bars in sorted(buckets.items())
        ]

        # ── 6. Persist derived bars ───────────────────────────────────────────
        await self._uow.ohlcv.bulk_upsert_derived(derived_bars)
        await self._uow.commit()

        log.info("derive_ohlcv.done", derived_count=len(derived_bars))
        return len(derived_bars)
