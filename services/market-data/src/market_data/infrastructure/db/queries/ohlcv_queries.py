"""TimescaleDB-optimised OHLCV query utilities.

All functions use **parameterized bindings only** — no Python string
formatting or f-strings with user-controlled values.  This prevents SQL
injection and allows the query planner to cache execution plans.

TimescaleDB notes:
- Range queries on ``bar_date`` benefit from hypertable **chunk pruning**:
  the planner restricts the query to only the chunks whose time range
  overlaps [start, end], dramatically reducing I/O for selective ranges.
- ``time_bucket()`` is a TimescaleDB / PostgreSQL extension aggregate that
  groups time-series data into fixed-width buckets (e.g., 5 minutes).

Required indexes:
- Primary key ``(instrument_id, timeframe, bar_date)`` — supports point
  and range lookups.
- ``ix_ohlcv_bars_instrument_bar_date (instrument_id, bar_date)`` — supports
  range queries filtered by instrument.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select, text

from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority
from market_data.infrastructure.db.models.ohlcv import OHLCVBarModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ── Timeframe → time_bucket interval mapping ──────────────────────────────────

_TIMEFRAME_INTERVAL: dict[str, str] = {
    "1m": "1 minute",
    "5m": "5 minutes",
    "15m": "15 minutes",
    "30m": "30 minutes",
    "1h": "1 hour",
    "4h": "4 hours",
    "1d": "1 day",
    "1w": "1 week",
    "1M": "1 month",
}


def _to_domain(row: OHLCVBarModel) -> OHLCVBar:
    return OHLCVBar(
        instrument_id=row.instrument_id,
        timeframe=Timeframe(row.timeframe),
        bar_date=row.bar_date,
        open=Decimal(str(row.open)),
        high=Decimal(str(row.high)),
        low=Decimal(str(row.low)),
        close=Decimal(str(row.close)),
        volume=int(row.volume) if row.volume is not None else 0,
        adjusted_close=Decimal(str(row.adjusted_close)) if row.adjusted_close is not None else None,
        source=row.source or "",
        provider_priority=ProviderPriority(provider="unknown", priority=int(row.provider_priority)),
    )


# ── Query functions ────────────────────────────────────────────────────────────


async def get_bars_by_range(
    session: AsyncSession,
    instrument_id: str,
    timeframe: Timeframe,
    start: date,
    end: date,
) -> list[OHLCVBar]:
    """Return bars for the given instrument/timeframe within [start, end].

    TimescaleDB chunk pruning eliminates chunks whose time range does not
    overlap [start_dt, end_dt], making this query O(matched chunks) rather
    than O(total data).

    All parameter bindings are parameterized — the ``instrument_id``,
    ``timeframe``, ``start``, and ``end`` values are never interpolated
    into the SQL string.
    """
    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC)
    result = await session.execute(
        select(OHLCVBarModel)
        .where(
            OHLCVBarModel.instrument_id == instrument_id,
            OHLCVBarModel.timeframe == str(timeframe),
            OHLCVBarModel.bar_date >= start_dt,
            OHLCVBarModel.bar_date <= end_dt,
        )
        .order_by(OHLCVBarModel.bar_date.asc())
    )
    return [_to_domain(row) for row in result.scalars().all()]


async def get_latest_bar(
    session: AsyncSession,
    instrument_id: str,
    timeframe: Timeframe,
) -> OHLCVBar | None:
    """Return the most recent bar for the given instrument/timeframe."""
    result = await session.execute(
        select(OHLCVBarModel)
        .where(
            OHLCVBarModel.instrument_id == instrument_id,
            OHLCVBarModel.timeframe == str(timeframe),
        )
        .order_by(OHLCVBarModel.bar_date.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return _to_domain(row) if row else None


async def get_bar_count(
    session: AsyncSession,
    instrument_id: str,
    timeframe: Timeframe,
) -> int:
    """Return the total number of stored bars for the given instrument/timeframe."""
    result = await session.execute(
        select(func.count())
        .select_from(OHLCVBarModel)
        .where(
            OHLCVBarModel.instrument_id == instrument_id,
            OHLCVBarModel.timeframe == str(timeframe),
        )
    )
    return int(result.scalar_one() or 0)


async def get_available_date_range(
    session: AsyncSession,
    instrument_id: str,
    timeframe: Timeframe,
) -> tuple[date, date] | None:
    """Return ``(min_date, max_date)`` for the instrument/timeframe, or ``None``."""
    result = await session.execute(
        select(
            func.min(OHLCVBarModel.bar_date),
            func.max(OHLCVBarModel.bar_date),
        ).where(
            OHLCVBarModel.instrument_id == instrument_id,
            OHLCVBarModel.timeframe == str(timeframe),
        )
    )
    min_dt: datetime | None
    max_dt: datetime | None
    min_dt, max_dt = result.one()
    if min_dt is None or max_dt is None:
        return None
    return (min_dt.date(), max_dt.date())


async def downsample_to_timeframe(
    session: AsyncSession,
    instrument_id: str,
    source_timeframe: Timeframe,
    target_timeframe: Timeframe,
    start: date,
    end: date,
) -> list[OHLCVBar]:
    """Resample OHLCV data from a finer to a coarser timeframe.

    Uses PostgreSQL ``time_bucket()`` (provided by TimescaleDB) to aggregate
    bars.  For example, calling with ``source_timeframe=Timeframe.ONE_MIN``
    and ``target_timeframe=Timeframe.FIVE_MIN`` produces 5-minute bars from
    stored 1-minute bars.

    All values are parameterized — the interval string is looked up from a
    safe static mapping and is never derived from user input.
    """
    interval = _TIMEFRAME_INTERVAL.get(str(target_timeframe), "1 day")
    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC)

    # Use text() with named bind parameters — no string interpolation of
    # user-controlled values.  The interval is from a static lookup table.
    stmt = text(
        "SELECT "
        "  time_bucket(:interval, bar_date) AS bucket_date, "
        "  :instrument_id AS instrument_id, "
        "  :target_timeframe AS timeframe, "
        "  (array_agg(open ORDER BY bar_date ASC))[1] AS open, "
        "  MAX(high) AS high, "
        "  MIN(low) AS low, "
        "  (array_agg(close ORDER BY bar_date DESC))[1] AS close, "
        "  SUM(volume) AS volume "
        "FROM ohlcv_bars "
        "WHERE instrument_id = :instrument_id "
        "  AND timeframe = :source_timeframe "
        "  AND bar_date >= :start_dt "
        "  AND bar_date <= :end_dt "
        "GROUP BY bucket_date "
        "ORDER BY bucket_date ASC"
    )
    result = await session.execute(
        stmt,
        {
            "interval": interval,
            "instrument_id": instrument_id,
            "target_timeframe": str(target_timeframe),
            "source_timeframe": str(source_timeframe),
            "start_dt": start_dt,
            "end_dt": end_dt,
        },
    )
    rows = result.mappings().all()
    return [
        OHLCVBar(
            instrument_id=instrument_id,
            timeframe=target_timeframe,
            bar_date=row["bucket_date"],
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
            volume=int(row["volume"]) if row["volume"] is not None else 0,
        )
        for row in rows
    ]
