"""Performance smoke test for ComputedMetricsBackfillWorker (PLAN-0089 Wave L-3).

QA L-3 finding #1 (non-blocking): the worker sweeps ~3000 instruments x 8
LATERAL-JOIN metrics x ~1100 daily bars at 02:00 UTC daily. Before this test
landed there was no committed evidence the sweep stays within budget, and no
``EXPLAIN ANALYZE`` reference for the slowest formula (``return_1y``).

This file adds a *smoke* threshold — NOT a production target. We seed 50
instruments x 800 daily bars (≈1.6% of production volume) and assert the full
sweep finishes inside 30 seconds. Production runtime at 3000 instruments is
expected to scale roughly linearly (~10x wall-clock, ≈5 minutes) given the
LATERAL JOIN is index-bounded on ``(instrument_id, bar_date DESC)``.

If this test starts taking >30 s with the current fixture size, that signals a
real regression worth investigating BEFORE the next production deploy — most
likely a missed index, a stat-staleness issue, or an accidental ``ORDER BY``
without index support.

Skip behaviour: requires Docker (testcontainers spawns Timescale). The shared
``_migrated_db`` session fixture in :mod:`tests.integration.conftest` handles
container lifecycle and Alembic head, so this test inherits the same skip
semantics as other ``pytest.mark.integration`` files in this directory.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from market_data.infrastructure.db.computed_metrics_worker import (
    ComputedMetricsBackfillOptions,
    run_computed_metrics_backfill,
)
from market_data.infrastructure.db.models.fundamental_metrics import FundamentalMetricModel
from market_data.infrastructure.db.models.instruments import InstrumentModel
from market_data.infrastructure.db.models.ohlcv import OHLCVBarModel
from market_data.infrastructure.db.models.securities import SecurityModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Slow + integration so this is skipped by default in fast CI lanes. Marks
# match other integration tests in this directory (see test_e2e_pipeline.py
# and test_outbox_integration.py).
pytestmark = [pytest.mark.integration, pytest.mark.slow]


# ── Tunables — keep small enough for CI but large enough to be representative ─

# Production has ~3000 instruments x 8 metrics = 24,000 metric rows per sweep.
# 50 x 8 = 400 rows is ~1.6% of that. Linear scaling assumed.
_FIXTURE_INSTRUMENTS = 50
# Production has ~1100 daily bars per instrument (≈4.5 years). 800 is enough
# to make every metric (incl. return_1y at 252 trading-day lookback) compute.
_BARS_PER_INSTRUMENT = 800
# Budget: 30 s smoke threshold. NOT a production SLO. Production target is
# < 15 min wall-clock for the full 3000-instrument sweep at 02:00 UTC.
_BUDGET_SECONDS = 30.0


async def _seed_instrument_with_bars(session, symbol: str, bar_count: int) -> str:
    """Insert one Security + Instrument + ``bar_count`` daily OHLCV bars.

    Bars walk backward from today and use a deterministic price walk so the
    perf test is reproducible. ``has_ohlcv = True`` is mandatory: the worker
    SQL filters on this flag.
    """
    sec = SecurityModel(name=f"Perf Test {symbol}")
    session.add(sec)
    await session.flush()

    instr = InstrumentModel(
        security_id=sec.id,
        symbol=symbol,
        exchange="XNAS",
        has_ohlcv=True,
    )
    session.add(instr)
    await session.flush()

    # Build bars in one ``add_all`` call for speed; SQLAlchemy batches the INSERT.
    today = datetime(2026, 5, 28, tzinfo=UTC)
    bars: list[OHLCVBarModel] = []
    for day_offset in range(bar_count):
        bar_date = today - timedelta(days=day_offset)
        # Deterministic price walk: starts at 100, ±0.1 per day.
        px = 100.0 + (day_offset % 50) * 0.1
        bars.append(
            OHLCVBarModel(
                instrument_id=instr.id,
                timeframe="1d",
                bar_date=bar_date,
                open=px,
                high=px + 0.5,
                low=px - 0.5,
                close=px,
                volume=1_000_000.0,
                adjusted_close=px,  # adj == close → no fallback triggered
                source="perf-test",
            )
        )
    session.add_all(bars)
    await session.flush()
    return instr.id


@pytest.mark.asyncio
async def test_computed_metrics_worker_perf_smoke(_migrated_db: str) -> None:
    """Full sweep over 50 instruments x 800 bars completes inside 30 s.

    Assertions:
      * ``runtime`` < 30 s (smoke threshold; production budget is ~15 min @ 3000).
      * ``metrics_written > 0`` (hard assertion — the BP-180 asyncpg uuid-cast
        fix is now in place, so the sweep MUST write rows; a 0 result is a
        regression, not a transient skip).
      * Summary reports the expected ``instruments_processed`` count.
      * ``fallback_adjusted_close_count == 0`` (all fixture bars have adj == close).
      * The ``fallback_adjusted_close_count`` field is present on the summary
        (the field the runbook tells operators to watch — its existence is
        the L-3 observability contract).

    Why we call the worker with ``continue_on_error=True`` (the default, also
    used by the production lifespan task in ``app.py``): the smoke threshold
    measures end-to-end wall-clock under the SAME failure semantics production
    uses. Strict mode would raise on the first transient asyncpg quirk and
    misrepresent the production duration.

    A failure of the time budget here means either a regression in the LATERAL
    JOIN plan, a stale index, or an accidental cross-product. Run
    ``EXPLAIN ANALYZE`` on the ``return_1y`` formula first — it is the most
    expensive of the 8 sweeps (252-day lookback, deepest LATERAL).
    """
    engine = create_async_engine(_migrated_db, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # ── Seed fixtures ────────────────────────────────────────────────────────
    async with factory() as session:
        for _i in range(_FIXTURE_INSTRUMENTS):
            # uuid4 hex keeps symbols globally unique even if other tests ran first.
            await _seed_instrument_with_bars(session, f"PF{uuid4().hex[:8].upper()}", _BARS_PER_INSTRUMENT)
        await session.commit()

    # ── Run sweep + measure wall-clock ──────────────────────────────────────
    # Use production defaults (continue_on_error=True) — see docstring above.
    started = time.monotonic()
    summary = await run_computed_metrics_backfill(
        factory,
        ComputedMetricsBackfillOptions(batch_size=500),
    )
    elapsed = time.monotonic() - started

    # ── Assertions ──────────────────────────────────────────────────────────
    # 1. Wall-clock budget. The primary regression tripwire.
    assert elapsed < _BUDGET_SECONDS, (
        f"Perf smoke FAILED: sweep took {elapsed:.2f}s, budget is {_BUDGET_SECONDS}s. "
        f"Production scaling implies this regresses to ~{elapsed * 60:.0f}s at 3000 instruments. "
        f"Run EXPLAIN ANALYZE on the return_1y LATERAL JOIN before merging."
    )

    # 2. Existence check on the summary field — ensures the L-3 observability
    # contract (runbook references this field name) does not silently drift.
    # This must hold regardless of whether batches succeeded.
    assert hasattr(summary, "fallback_adjusted_close_count")
    assert hasattr(summary, "metrics_written")
    assert hasattr(summary, "instruments_processed")
    assert hasattr(summary, "failed_instruments")

    # 3. Fallback counter is the metric the runbook tells operators to watch.
    # All fixture bars have adj == close, so the WORKER must report 0 here.
    # A non-zero value indicates the adj-fallback detection path is broken.
    assert summary.fallback_adjusted_close_count == 0, (
        "Fixture bars have adjusted_close == close, so fallback counter must be 0. "
        "A non-zero value indicates the worker is mis-detecting NULL adj_close."
    )

    # 4. Worker must report forward progress. With the BP-180 asyncpg uuid-cast
    # fix in place (WL-3 fix-bp180 merge), the SQL no longer aborts on the
    # ``:start_id IS NULL`` parameter and the sweep writes metrics on every
    # run. A ``metrics_written == 0`` outcome now indicates a real regression
    # (e.g. another asyncpg parameter quirk, a stat-staleness issue, or a
    # silent rollback) and must fail the test rather than be silently skipped.
    assert summary.metrics_written > 0, (
        f"expected metrics written, got {summary.metrics_written}. "
        "BP-180 asyncpg uuid-cast fix is in place — a 0 result indicates a new regression."
    )
    assert summary.instruments_processed >= _FIXTURE_INSTRUMENTS, (
        f"Worker reported instruments_processed={summary.instruments_processed} "
        f"but {_FIXTURE_INSTRUMENTS} fixture instruments were seeded."
    )

    # 5. Confirm at least one row per metric type made it to disk. We do NOT
    # assert an exact count (the worker may legitimately skip metrics for
    # instruments with < lookback history) but with BP-180 fixed every metric
    # name must have at least one row.
    async with factory() as session:
        for metric_name in (
            "return_1m",
            "return_3m",
            "return_6m",
            "return_ytd",
            "return_1y",
            "distance_52w_high",
            "distance_52w_low",
            "volatility_30d",
        ):
            row = (
                await session.execute(
                    select(FundamentalMetricModel).where(FundamentalMetricModel.metric == metric_name).limit(1)
                )
            ).scalar_one_or_none()
            assert row is not None, f"No fundamental_metrics row for metric={metric_name} — formula regressed"

    await engine.dispose()
