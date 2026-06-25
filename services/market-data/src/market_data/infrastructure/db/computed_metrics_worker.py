"""Compute and upsert the derived ``fundamental_metrics`` rows from OHLCV.

As of the L-3 ops follow-up the worker emits **10** metric names: 5 period
returns (1M/3M/6M/1Y/3Y), YTD return, 2 distance-from-52W (high/low),
``volatility_30d`` (annualised 30-trading-day realised vol), and
``returns_adjustment_quality`` (per-instrument 1.0/0.0 flag marking whether
returns were computed on real adjusted_close or fell back to raw close).

PLAN-0089 Wave L-3 (T-WL3-01). Modelled on
:mod:`market_data.infrastructure.db.backfill_fundamental_metrics` and on the
LATERAL-JOIN pattern of
``ohlcv_repo.get_period_movers`` (services/market-data/src/market_data/
infrastructure/db/repositories/ohlcv_repo.py:292-339).

Inputs:
    * ``ohlcv_bars`` rows (timeframe='1d'), keyed by ``instrument_id``.

Outputs (per instrument, written to ``fundamental_metrics`` with
``period_type='SNAPSHOT'``, ``section='computed_returns'``):
    * ``dist_from_52w_high_pct = (close_T / max_close_252d) - 1``
    * ``dist_from_52w_low_pct  = (close_T / min_close_252d) - 1``
    * ``return_1m  = (close_T / close_{T-30d}) - 1``
    * ``return_3m  = (close_T / close_{T-90d}) - 1``
    * ``return_6m  = (close_T / close_{T-182d}) - 1``
    * ``return_ytd = (close_T / close_{first trading day of year}) - 1``
    * ``return_1y  = (close_T / close_{T-365d}) - 1``
    * ``return_3y  = (close_T / close_{T-1095d}) - 1``

WHY ratio-1 instead of ((T-Tn)/Tn)*100: keeps unit consistent across all 8
fields (fraction, not percent). The screen_field_metadata sets unit="%" and
the frontend multiplies by 100 on render — same convention as
``daily_return`` (already a fraction).

WHY ``COALESCE(adjusted_close, close)`` (audit §7.3): ``adjusted_close``
is the correct split/dividend-adjusted price for ratio returns, but the
column is nullable. The worker COALESCEs to ``close`` and counts
instruments where the fallback applied so an audit can run later.

WHY LATERAL JOIN ``bar_date <= latest.bar_date - INTERVAL '1 day' * N``: the
predicate matches the most recent bar at or before the lookback date. This
gracefully degrades to the prior trading day for weekends/holidays without
needing a calendar table (audit §7.2).

WHY one SQL pass per metric group: each metric has a different
lookback / aggregation shape (point lookup vs window max/min vs YTD anchor),
so a single CTE would be more complex than 8 focused statements and harder
to read. Each statement is ~500 ms at current instrument volume.

Idempotency: writes use
``PgFundamentalMetricsRepository.upsert_metrics`` which performs
``ON CONFLICT (instrument_id, as_of_date, metric, period_type) DO UPDATE``
(see ``fundamental_metrics_repo.py``). Re-running the worker on identical
input is a no-op modulo the ``ingested_at`` timestamp.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date as date_type
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from common.time import utc_now  # type: ignore[import-untyped]
from market_data.infrastructure.db.metric_extractor import MetricRow
from market_data.infrastructure.db.repositories.fundamental_metrics_repo import PgFundamentalMetricsRepository
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)


# Period/section constants — match existing ``metric_extractor.MetricRow`` shape.
_PERIOD_TYPE = "SNAPSHOT"
_SECTION = "computed_returns"


# Lookback configuration. Calendar-day lookbacks; the LATERAL JOIN selects
# the most recent ``ohlcv_bars`` row at or before ``latest.bar_date - N days``,
# which absorbs weekends/holidays without a calendar table.
# Lookbacks chosen to match common finance conventions (30d ≈ 1M, 90d ≈ 3M).
_PERIOD_RETURN_LOOKBACKS: tuple[tuple[str, int], ...] = (
    ("return_1m", 30),
    ("return_3m", 90),
    ("return_6m", 182),
    ("return_1y", 365),
    ("return_3y", 1095),
)

# 52-week window length used for distance-from-high/low metrics.
_WINDOW_52W_DAYS = 365

# Number of most-recent trading-day bars used for the 30-day realised
# volatility. We count BARS (not calendar days) so the window is ~30 trading
# sessions regardless of weekends/holidays. 21 bars ≈ 1 calendar month; 30 bars
# is the conventional "30-day vol" lookback most finance feeds use.
_VOLATILITY_BARS = 30

# Trading days per year for annualising daily-return stddev (sqrt(252)).
_TRADING_DAYS_PER_YEAR = 252

# Metric name for the per-instrument adjusted-close data-quality flag.
# 1.0 = the latest bar carries a real split/dividend-adjusted close (returns are
# correct across corporate actions); 0.0 = adjusted_close was NULL so returns
# were computed on RAW close and may be wrong across splits/dividends. Surfaced
# in the screener so unadjusted returns are flagged rather than shown as truth.
_ADJUSTMENT_QUALITY_METRIC = "returns_adjustment_quality"

# Metric name for trailing 30-trading-day annualised realised volatility.
_VOLATILITY_METRIC = "volatility_30d"


@dataclass(frozen=True, slots=True)
class ComputedMetricsBackfillOptions:
    """Tunable knobs for one backfill invocation."""

    batch_size: int = 500
    # Optional resumable cursor: when set, restricts processing to instruments
    # whose id > ``start_instrument_id``. ``None`` = start from beginning.
    start_instrument_id: str | None = None
    continue_on_error: bool = True


@dataclass(slots=True)
class ComputedMetricsBackfillSummary:
    """Per-run telemetry returned to the caller (and emitted as a log line)."""

    started_at: str
    completed_at: str | None
    runtime_seconds: float
    instruments_processed: int
    metrics_written: int
    # Number of (instrument, metric) pairs skipped because the instrument has
    # insufficient history for that specific lookback. Per-metric, per-instrument.
    skipped_short_history_count: int
    # Number of distinct instruments where any metric used ``COALESCE`` to fall
    # back to ``close`` because ``adjusted_close`` was NULL. Logged at WARNING
    # at the end of each run so an operator can spot a regression.
    fallback_adjusted_close_count: int
    failed_instruments: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Each formula has the same LATERAL-JOIN shape (latest bar + reference bar),
# parameterized by a single lookback length. ``COALESCE(adjusted_close, close)``
# is applied to BOTH the numerator and denominator so the ratio is consistent.
_RETURN_FORMULA_SQL = """
SELECT
    i.id AS instrument_id,
    latest.bar_date AS as_of_date,
    (latest.px / NULLIF(prev.px, 0)) - 1.0 AS value_numeric,
    (latest.adj_is_null OR prev.adj_is_null) AS used_fallback
FROM instruments i
JOIN LATERAL (
    SELECT
        COALESCE(adjusted_close, close) AS px,
        adjusted_close IS NULL AS adj_is_null,
        bar_date
    FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = '1d'
    ORDER BY bar_date DESC
    LIMIT 1
) latest ON true
JOIN LATERAL (
    SELECT
        COALESCE(adjusted_close, close) AS px,
        adjusted_close IS NULL AS adj_is_null
    FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = '1d'
      AND bar_date <= latest.bar_date - (INTERVAL '1 day' * :lookback_days)
    ORDER BY bar_date DESC
    LIMIT 1
) prev ON true
WHERE i.has_ohlcv = true
  -- BP-180: asyncpg cannot infer the type of `:start_id` when it appears as a
  -- bare parameter on the IS NULL side of an OR (the planner sees no column
  -- context). The cast MUST wrap both sides of the OR so asyncpg infers uuid
  -- even when the value is None — otherwise the predicate fails silently and
  -- the cursor scan returns zero rows (the bug this commit fixes).
  AND (CAST(:start_id AS uuid) IS NULL OR i.id > CAST(:start_id AS uuid))
ORDER BY i.id ASC
LIMIT :batch_size
OFFSET :offset
"""


# 52-week distance: latest close vs MAX/MIN of close over the trailing 365d
# window. Returns a single row per instrument. NULL when fewer than 1y of
# bars are available (the window is empty → MAX/MIN are NULL).
_DISTANCE_52W_SQL = """
SELECT
    i.id AS instrument_id,
    latest.bar_date AS as_of_date,
    (latest.px / NULLIF(window_max.px, 0)) - 1.0 AS dist_from_52w_high_pct,
    (latest.px / NULLIF(window_min.px, 0)) - 1.0 AS dist_from_52w_low_pct,
    latest.adj_is_null AS used_fallback
FROM instruments i
JOIN LATERAL (
    SELECT
        COALESCE(adjusted_close, close) AS px,
        adjusted_close IS NULL AS adj_is_null,
        bar_date
    FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = '1d'
    ORDER BY bar_date DESC
    LIMIT 1
) latest ON true
JOIN LATERAL (
    SELECT MAX(COALESCE(adjusted_close, close)) AS px
    FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = '1d'
      AND bar_date > latest.bar_date - (INTERVAL '1 day' * :window_days)
      AND bar_date <= latest.bar_date
) window_max ON true
JOIN LATERAL (
    SELECT MIN(COALESCE(adjusted_close, close)) AS px
    FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = '1d'
      AND bar_date > latest.bar_date - (INTERVAL '1 day' * :window_days)
      AND bar_date <= latest.bar_date
) window_min ON true
WHERE i.has_ohlcv = true
  AND (CAST(:start_id AS uuid) IS NULL OR i.id > CAST(:start_id AS uuid))
ORDER BY i.id ASC
LIMIT :batch_size
OFFSET :offset
"""


# YTD return uses a calendar anchor: the most recent bar at or AFTER
# DATE_TRUNC('year', latest.bar_date). If the first trading day of the year
# is a holiday, we pick the next trading day — same "≤" inversion as the
# lookback queries, but anchored on the calendar.
_YTD_RETURN_SQL = """
SELECT
    i.id AS instrument_id,
    latest.bar_date AS as_of_date,
    (latest.px / NULLIF(anchor.px, 0)) - 1.0 AS value_numeric,
    (latest.adj_is_null OR anchor.adj_is_null) AS used_fallback
FROM instruments i
JOIN LATERAL (
    SELECT
        COALESCE(adjusted_close, close) AS px,
        adjusted_close IS NULL AS adj_is_null,
        bar_date
    FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = '1d'
    ORDER BY bar_date DESC
    LIMIT 1
) latest ON true
JOIN LATERAL (
    SELECT
        COALESCE(adjusted_close, close) AS px,
        adjusted_close IS NULL AS adj_is_null
    FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = '1d'
      AND bar_date >= DATE_TRUNC('year', latest.bar_date)
    ORDER BY bar_date ASC
    LIMIT 1
) anchor ON true
WHERE i.has_ohlcv = true
  AND (CAST(:start_id AS uuid) IS NULL OR i.id > CAST(:start_id AS uuid))
ORDER BY i.id ASC
LIMIT :batch_size
OFFSET :offset
"""


# 30-trading-day realised volatility: stddev of consecutive daily simple
# returns over the most recent :vol_bars bars, annualised by sqrt(252).
#
# WHY a windowed CTE (not a self-join): we take the last :vol_bars bars per
# instrument (ROW_NUMBER), compute each bar's return vs the prior bar via LAG,
# then STDDEV_SAMP the returns. ``stddev_samp`` (n-1 denominator) is the
# conventional sample stddev for realised vol. NULL when fewer than 2 returns
# exist (a single bar has no return) — the row is then skipped like any other
# short-history metric.
#
# WHY adjusted_close fallback here too: consistent with the return metrics so a
# split inside the 30-bar window does not inflate volatility on raw close.
_VOLATILITY_30D_SQL = """
WITH ranked AS (
    SELECT
        i.id AS instrument_id,
        ob.bar_date,
        COALESCE(ob.adjusted_close, ob.close) AS px,
        ROW_NUMBER() OVER (PARTITION BY i.id ORDER BY ob.bar_date DESC) AS rn
    FROM instruments i
    JOIN ohlcv_bars ob
      ON ob.instrument_id = i.id AND ob.timeframe = '1d'
    WHERE i.has_ohlcv = true
      AND (CAST(:start_id AS uuid) IS NULL OR i.id > CAST(:start_id AS uuid))
),
windowed AS (
    SELECT instrument_id, bar_date, px
    FROM ranked
    WHERE rn <= :vol_bars
),
returns AS (
    SELECT
        instrument_id,
        (px / NULLIF(LAG(px) OVER (PARTITION BY instrument_id ORDER BY bar_date), 0)) - 1.0 AS r
    FROM windowed
),
latest AS (
    SELECT i.id AS instrument_id, MAX(ob.bar_date) AS as_of_date
    FROM instruments i
    JOIN ohlcv_bars ob ON ob.instrument_id = i.id AND ob.timeframe = '1d'
    WHERE i.has_ohlcv = true
      AND (CAST(:start_id AS uuid) IS NULL OR i.id > CAST(:start_id AS uuid))
    GROUP BY i.id
)
SELECT
    l.instrument_id AS instrument_id,
    l.as_of_date AS as_of_date,
    STDDEV_SAMP(rt.r) * sqrt(:trading_days) AS value_numeric
FROM latest l
JOIN returns rt ON rt.instrument_id = l.instrument_id
WHERE rt.r IS NOT NULL
GROUP BY l.instrument_id, l.as_of_date
ORDER BY l.instrument_id ASC
LIMIT :batch_size
OFFSET :offset
"""


# Per-instrument adjusted-close data-quality flag from the LATEST daily bar:
# 1.0 when adjusted_close is present, 0.0 when it is NULL (returns fell back to
# raw close for that instrument). One row per instrument with OHLCV.
_ADJUSTMENT_QUALITY_SQL = """
SELECT
    i.id AS instrument_id,
    latest.bar_date AS as_of_date,
    CASE WHEN latest.adjusted_close IS NULL THEN 0.0 ELSE 1.0 END AS value_numeric
FROM instruments i
JOIN LATERAL (
    SELECT adjusted_close, bar_date
    FROM ohlcv_bars
    WHERE instrument_id = i.id AND timeframe = '1d'
    ORDER BY bar_date DESC
    LIMIT 1
) latest ON true
WHERE i.has_ohlcv = true
  AND (CAST(:start_id AS uuid) IS NULL OR i.id > CAST(:start_id AS uuid))
ORDER BY i.id ASC
LIMIT :batch_size
OFFSET :offset
"""


async def _fetch_period_return_batch(
    session: AsyncSession,
    lookback_days: int,
    start_id: str | None,
    offset: int,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Return one batch of (instrument_id, value, used_fallback) rows for a lookback."""
    result = await session.execute(
        text(_RETURN_FORMULA_SQL),
        {
            "lookback_days": lookback_days,
            "start_id": start_id,
            "batch_size": batch_size,
            "offset": offset,
        },
    )
    return [dict(row) for row in result.mappings().all()]


async def _fetch_ytd_return_batch(
    session: AsyncSession,
    start_id: str | None,
    offset: int,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Return one batch of YTD-return rows."""
    result = await session.execute(
        text(_YTD_RETURN_SQL),
        {"start_id": start_id, "batch_size": batch_size, "offset": offset},
    )
    return [dict(row) for row in result.mappings().all()]


async def _fetch_distance_52w_batch(
    session: AsyncSession,
    start_id: str | None,
    offset: int,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Return one batch of 52-week distance rows."""
    result = await session.execute(
        text(_DISTANCE_52W_SQL),
        {
            "window_days": _WINDOW_52W_DAYS,
            "start_id": start_id,
            "batch_size": batch_size,
            "offset": offset,
        },
    )
    return [dict(row) for row in result.mappings().all()]


async def _fetch_volatility_30d_batch(
    session: AsyncSession,
    start_id: str | None,
    offset: int,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Return one batch of 30-trading-day annualised volatility rows."""
    result = await session.execute(
        text(_VOLATILITY_30D_SQL),
        {
            "vol_bars": _VOLATILITY_BARS,
            "trading_days": _TRADING_DAYS_PER_YEAR,
            "start_id": start_id,
            "batch_size": batch_size,
            "offset": offset,
        },
    )
    return [dict(row) for row in result.mappings().all()]


async def _fetch_adjustment_quality_batch(
    session: AsyncSession,
    start_id: str | None,
    offset: int,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Return one batch of per-instrument adjusted-close quality flags (1.0/0.0)."""
    result = await session.execute(
        text(_ADJUSTMENT_QUALITY_SQL),
        {"start_id": start_id, "batch_size": batch_size, "offset": offset},
    )
    return [dict(row) for row in result.mappings().all()]


def _row_to_metric(
    instrument_id: str,
    as_of_date: date_type,
    metric: str,
    value: Any,
    ingested_at: Any,
) -> MetricRow | None:
    """Build a MetricRow from a raw query row. Returns None when value is NULL.

    NULL means insufficient history for the lookback (no prior bar matched
    the ``bar_date <= ...`` predicate, so the LATERAL JOIN omitted the row).
    We intentionally do NOT write a NULL row — leaving the absent key absent
    is more informative than persisting a tombstone (audit §6, "<30 d
    history → NULL" expectation matches).
    """
    if value is None:
        return None
    try:
        value_decimal = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    return MetricRow(
        instrument_id=str(instrument_id),
        as_of_date=as_of_date,
        metric=metric,
        value_numeric=value_decimal,
        value_text=None,
        period_type=_PERIOD_TYPE,
        section=_SECTION,
        ingested_at=ingested_at,
    )


async def run_computed_metrics_backfill(
    session_factory: async_sessionmaker[AsyncSession],
    options: ComputedMetricsBackfillOptions | None = None,
) -> ComputedMetricsBackfillSummary:
    """Compute and upsert the derived metrics for every instrument with OHLCV.

    Returns a :class:`ComputedMetricsBackfillSummary` with per-run telemetry.
    Logs at INFO on completion and WARNING when ``adjusted_close`` fallback
    occurred (audit §7.3).
    """
    opts = options or ComputedMetricsBackfillOptions()
    started_at = utc_now()
    ingested_at = started_at

    instruments_seen: set[str] = set()
    metrics_written = 0
    skipped_short_history = 0
    fallback_instruments: set[str] = set()
    failed_instruments = 0

    async with session_factory() as session:
        repo = PgFundamentalMetricsRepository(session)

        # --- 1) Period returns (1M / 3M / 6M / 1Y / 3Y) --------------------
        for metric_name, lookback_days in _PERIOD_RETURN_LOOKBACKS:
            offset = 0
            while True:
                try:
                    rows = await _fetch_period_return_batch(
                        session, lookback_days, opts.start_instrument_id, offset, opts.batch_size
                    )
                except Exception as exc:  # continue-on-error semantics
                    failed_instruments += 1
                    logger.error(
                        "computed_metrics_backfill.batch_failed",
                        metric=metric_name,
                        offset=offset,
                        error=str(exc),
                    )
                    if not opts.continue_on_error:
                        raise
                    break

                if not rows:
                    break

                metric_batch: list[MetricRow] = []
                for row in rows:
                    instrument_id = str(row["instrument_id"])
                    instruments_seen.add(instrument_id)
                    if row.get("used_fallback"):
                        fallback_instruments.add(instrument_id)
                    metric_row = _row_to_metric(
                        instrument_id,
                        row["as_of_date"].date() if hasattr(row["as_of_date"], "date") else row["as_of_date"],
                        metric_name,
                        row["value_numeric"],
                        ingested_at,
                    )
                    if metric_row is None:
                        skipped_short_history += 1
                        logger.debug(
                            "computed_metrics_backfill.skipped_short_history",
                            metric=metric_name,
                            instrument_id=instrument_id,
                        )
                        continue
                    metric_batch.append(metric_row)

                if metric_batch:
                    await repo.upsert_metrics(metric_batch)
                    metrics_written += len(metric_batch)
                    await session.commit()

                if len(rows) < opts.batch_size:
                    break
                offset += opts.batch_size

            logger.info(
                "computed_metrics_backfill.metric_completed",
                metric=metric_name,
                lookback_days=lookback_days,
                instruments_seen=len(instruments_seen),
                metrics_written=metrics_written,
            )

        # --- 2) YTD return -------------------------------------------------
        offset = 0
        while True:
            try:
                rows = await _fetch_ytd_return_batch(session, opts.start_instrument_id, offset, opts.batch_size)
            except Exception as exc:
                failed_instruments += 1
                logger.error(
                    "computed_metrics_backfill.batch_failed", metric="return_ytd", offset=offset, error=str(exc)
                )
                if not opts.continue_on_error:
                    raise
                break

            if not rows:
                break

            metric_batch = []
            for row in rows:
                instrument_id = str(row["instrument_id"])
                instruments_seen.add(instrument_id)
                if row.get("used_fallback"):
                    fallback_instruments.add(instrument_id)
                metric_row = _row_to_metric(
                    instrument_id,
                    row["as_of_date"].date() if hasattr(row["as_of_date"], "date") else row["as_of_date"],
                    "return_ytd",
                    row["value_numeric"],
                    ingested_at,
                )
                if metric_row is None:
                    skipped_short_history += 1
                    continue
                metric_batch.append(metric_row)

            if metric_batch:
                await repo.upsert_metrics(metric_batch)
                metrics_written += len(metric_batch)
                await session.commit()

            if len(rows) < opts.batch_size:
                break
            offset += opts.batch_size

        # --- 3) 52-week distance (high + low in one query) -----------------
        offset = 0
        while True:
            try:
                rows = await _fetch_distance_52w_batch(session, opts.start_instrument_id, offset, opts.batch_size)
            except Exception as exc:
                failed_instruments += 1
                logger.error(
                    "computed_metrics_backfill.batch_failed",
                    metric="dist_from_52w_high_pct/dist_from_52w_low_pct",
                    offset=offset,
                    error=str(exc),
                )
                if not opts.continue_on_error:
                    raise
                break

            if not rows:
                break

            metric_batch = []
            for row in rows:
                instrument_id = str(row["instrument_id"])
                instruments_seen.add(instrument_id)
                if row.get("used_fallback"):
                    fallback_instruments.add(instrument_id)
                as_of = row["as_of_date"].date() if hasattr(row["as_of_date"], "date") else row["as_of_date"]
                high_row = _row_to_metric(
                    instrument_id, as_of, "dist_from_52w_high_pct", row["dist_from_52w_high_pct"], ingested_at
                )
                low_row = _row_to_metric(
                    instrument_id, as_of, "dist_from_52w_low_pct", row["dist_from_52w_low_pct"], ingested_at
                )
                if high_row is None:
                    skipped_short_history += 1
                else:
                    metric_batch.append(high_row)
                if low_row is None:
                    skipped_short_history += 1
                else:
                    metric_batch.append(low_row)

            if metric_batch:
                await repo.upsert_metrics(metric_batch)
                metrics_written += len(metric_batch)
                await session.commit()

            if len(rows) < opts.batch_size:
                break
            offset += opts.batch_size

        # --- 4) 30-trading-day annualised realised volatility --------------
        offset = 0
        while True:
            try:
                rows = await _fetch_volatility_30d_batch(session, opts.start_instrument_id, offset, opts.batch_size)
            except Exception as exc:
                failed_instruments += 1
                logger.error(
                    "computed_metrics_backfill.batch_failed", metric=_VOLATILITY_METRIC, offset=offset, error=str(exc)
                )
                if not opts.continue_on_error:
                    raise
                break

            if not rows:
                break

            metric_batch = []
            for row in rows:
                instrument_id = str(row["instrument_id"])
                instruments_seen.add(instrument_id)
                metric_row = _row_to_metric(
                    instrument_id,
                    row["as_of_date"].date() if hasattr(row["as_of_date"], "date") else row["as_of_date"],
                    _VOLATILITY_METRIC,
                    row["value_numeric"],
                    ingested_at,
                )
                if metric_row is None:
                    skipped_short_history += 1
                    continue
                metric_batch.append(metric_row)

            if metric_batch:
                await repo.upsert_metrics(metric_batch)
                metrics_written += len(metric_batch)
                await session.commit()

            if len(rows) < opts.batch_size:
                break
            offset += opts.batch_size

        # --- 5) Per-instrument adjusted-close data-quality flag ------------
        # WHY a persisted metric (audit Task 1 option c): when adjusted_close is
        # NULL the returns/52W metrics above silently used raw close, which is
        # WRONG across splits/dividends. Rather than show those returns as truth,
        # we persist a per-instrument quality flag (1.0=adjusted, 0.0=raw-close
        # fallback) so the screener can badge "unadjusted" instead of lying.
        # The run-level ``fallback_adjusted_close_count`` already tracks the
        # aggregate; this exposes it per instrument for the UI + filtering.
        offset = 0
        while True:
            try:
                rows = await _fetch_adjustment_quality_batch(session, opts.start_instrument_id, offset, opts.batch_size)
            except Exception as exc:
                failed_instruments += 1
                logger.error(
                    "computed_metrics_backfill.batch_failed",
                    metric=_ADJUSTMENT_QUALITY_METRIC,
                    offset=offset,
                    error=str(exc),
                )
                if not opts.continue_on_error:
                    raise
                break

            if not rows:
                break

            metric_batch = []
            for row in rows:
                instrument_id = str(row["instrument_id"])
                instruments_seen.add(instrument_id)
                metric_row = _row_to_metric(
                    instrument_id,
                    row["as_of_date"].date() if hasattr(row["as_of_date"], "date") else row["as_of_date"],
                    _ADJUSTMENT_QUALITY_METRIC,
                    row["value_numeric"],
                    ingested_at,
                )
                if metric_row is None:
                    skipped_short_history += 1
                    continue
                metric_batch.append(metric_row)

            if metric_batch:
                await repo.upsert_metrics(metric_batch)
                metrics_written += len(metric_batch)
                await session.commit()

            if len(rows) < opts.batch_size:
                break
            offset += opts.batch_size

    completed_at = utc_now()
    summary = ComputedMetricsBackfillSummary(
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat(),
        runtime_seconds=float((completed_at - started_at).total_seconds()),
        instruments_processed=len(instruments_seen),
        metrics_written=metrics_written,
        skipped_short_history_count=skipped_short_history,
        fallback_adjusted_close_count=len(fallback_instruments),
        failed_instruments=failed_instruments,
    )

    # Per audit §7.3: a non-trivial ``adjusted_close`` fallback rate warrants
    # operator attention because it indicates the OHLCV ingest pipeline is
    # not consistently populating split-adjusted prices.
    if summary.fallback_adjusted_close_count > 0:
        logger.warning(
            "computed_metrics_backfill.adjusted_close_fallback",
            fallback_count=summary.fallback_adjusted_close_count,
            instruments_processed=summary.instruments_processed,
        )

    logger.info("computed_metrics_backfill.completed", **summary.to_dict())
    return summary
