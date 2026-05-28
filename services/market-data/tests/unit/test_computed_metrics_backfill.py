"""Unit tests for ComputedMetricsBackfillWorker (PLAN-0089 Wave L-3).

Focus areas:
  * ``_row_to_metric`` — NULL input → None (insufficient history), value coerces
    to Decimal, MetricRow shape matches the upstream upsert contract.
  * ``run_computed_metrics_backfill`` — empty result path: 0 metrics_written,
    fallback counter is 0, summary contract is intact (idempotency: a 2nd run
    over the same empty set produces identical summary modulo timestamps).
  * Scheduler helper ``_seconds_until_next_hour_utc`` from ``app.py`` —
    correctly computes the gap to the next 02:00 UTC slot for several
    clock positions.

Strategy:
  The SQL queries (LATERAL JOINs over ohlcv_bars) are integration-test
  territory (they need a Postgres instance + bar data). Here we use a stub
  ``session_factory`` that returns empty result-sets so the worker traces all
  branches (every metric loop completes, ``upsert_metrics`` is never called,
  summary is built). Formula correctness is covered by integration tests.

WHY this split: per Worldview's testing pyramid (AGENTS.md), unit tests must
not depend on Postgres; integration tests run via ``ALEMBIC_ENABLED=true``
with a live container. The 8 LATERAL-JOIN formulas are SQL-pure — there is no
Python logic to mock per metric, so unit-coverage gain from re-implementing
the math in Python (and then mocking it back) is negative.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.app import _seconds_until_next_hour_utc
from market_data.infrastructure.db.computed_metrics_worker import (
    ComputedMetricsBackfillOptions,
    _row_to_metric,
    run_computed_metrics_backfill,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _row_to_metric — formula edge cases
# ---------------------------------------------------------------------------


def test_row_to_metric_null_value_returns_none() -> None:
    """NULL numeric value (insufficient history for the lookback) → None.

    Audit §6: "<30 d history → NULL" expectation; the worker must NOT persist
    a tombstone row when the LATERAL JOIN omitted the lookback bar.
    """
    ingested_at = datetime(2026, 5, 28, tzinfo=UTC)
    assert _row_to_metric("inst-1", date(2026, 5, 28), "return_1m", None, ingested_at) is None


def test_row_to_metric_valid_value_returns_metric_row() -> None:
    """Valid numeric value → MetricRow with Decimal value and SNAPSHOT period_type."""
    ingested_at = datetime(2026, 5, 28, tzinfo=UTC)
    row = _row_to_metric("inst-1", date(2026, 5, 28), "return_1m", 0.0523, ingested_at)
    assert row is not None
    assert row.instrument_id == "inst-1"
    assert row.metric == "return_1m"
    assert row.period_type == "SNAPSHOT"
    assert row.section == "computed_returns"
    assert row.value_numeric == Decimal("0.0523")
    assert row.value_text is None


def test_row_to_metric_decimal_str_input_coerces() -> None:
    """A numeric string (Decimal-like) input coerces cleanly to Decimal."""
    ingested_at = datetime(2026, 5, 28, tzinfo=UTC)
    row = _row_to_metric("inst-1", date(2026, 5, 28), "return_3m", "0.10", ingested_at)
    assert row is not None
    assert row.value_numeric == Decimal("0.10")


def test_row_to_metric_invalid_value_returns_none() -> None:
    """Uncoercible value → None (defensive: keeps the upsert batch clean)."""
    ingested_at = datetime(2026, 5, 28, tzinfo=UTC)
    assert _row_to_metric("inst-1", date(2026, 5, 28), "return_1m", "not-a-number", ingested_at) is None


# ---------------------------------------------------------------------------
# run_computed_metrics_backfill — empty path + idempotency
# ---------------------------------------------------------------------------


def _make_empty_session_factory() -> Any:
    """Build a session_factory whose every execute call returns an empty result.

    The worker's batching loop terminates on the first empty batch, so the
    8 metrics each take exactly one execute call. We return a fresh
    MagicMock per execute so SQLAlchemy result interface coverage is uniform.
    """

    async def _execute(_stmt: Any, _params: Any | None = None) -> MagicMock:
        result = MagicMock()
        result.mappings = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        result.all = MagicMock(return_value=[])
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


@pytest.mark.asyncio
async def test_backfill_empty_ohlcv_writes_no_metrics() -> None:
    """Empty ohlcv_bars → 0 metrics_written, 0 instruments_processed."""
    factory = _make_empty_session_factory()
    summary = await run_computed_metrics_backfill(factory)
    assert summary.metrics_written == 0
    assert summary.instruments_processed == 0
    assert summary.failed_instruments == 0
    assert summary.fallback_adjusted_close_count == 0
    assert summary.skipped_short_history_count == 0


@pytest.mark.asyncio
async def test_backfill_idempotent_summary_contract() -> None:
    """Running twice on identical empty input yields identical summary modulo time.

    Idempotency check: metrics_written, skipped_short_history_count,
    fallback_adjusted_close_count must be byte-identical between runs.
    """
    factory = _make_empty_session_factory()
    s1 = await run_computed_metrics_backfill(factory)
    s2 = await run_computed_metrics_backfill(factory)
    assert s1.metrics_written == s2.metrics_written
    assert s1.skipped_short_history_count == s2.skipped_short_history_count
    assert s1.fallback_adjusted_close_count == s2.fallback_adjusted_close_count
    assert s1.instruments_processed == s2.instruments_processed


@pytest.mark.asyncio
async def test_backfill_options_continue_on_error_true_by_default() -> None:
    """Default ComputedMetricsBackfillOptions has continue_on_error=True."""
    opts = ComputedMetricsBackfillOptions()
    assert opts.continue_on_error is True
    assert opts.batch_size == 500
    assert opts.start_instrument_id is None


# ---------------------------------------------------------------------------
# Scheduler helper — _seconds_until_next_hour_utc
# ---------------------------------------------------------------------------


def test_seconds_until_next_hour_before_target() -> None:
    """At 01:00 UTC, time until 02:00 UTC same day = 3600s."""
    now = datetime(2026, 5, 28, 1, 0, 0, tzinfo=UTC)
    assert _seconds_until_next_hour_utc(2, now) == 3600.0


def test_seconds_until_next_hour_at_target() -> None:
    """At exactly 02:00 UTC, time until next 02:00 UTC = 86400s (full day)."""
    now = datetime(2026, 5, 28, 2, 0, 0, tzinfo=UTC)
    assert _seconds_until_next_hour_utc(2, now) == 86400.0


def test_seconds_until_next_hour_after_target() -> None:
    """At 03:00 UTC, next 02:00 slot is tomorrow → 23h = 82800s."""
    now = datetime(2026, 5, 28, 3, 0, 0, tzinfo=UTC)
    assert _seconds_until_next_hour_utc(2, now) == 23 * 3600


def test_seconds_until_next_hour_near_midnight() -> None:
    """At 23:30 UTC, next 02:00 slot is 2h30m away."""
    now = datetime(2026, 5, 28, 23, 30, 0, tzinfo=UTC)
    assert _seconds_until_next_hour_utc(2, now) == 2.5 * 3600


def test_seconds_until_next_hour_alternate_target_hour() -> None:
    """COMPUTED_METRICS_REFRESH_HOUR_UTC override still routes correctly (e.g. 14h)."""
    now = datetime(2026, 5, 28, 10, 0, 0, tzinfo=UTC)
    assert _seconds_until_next_hour_utc(14, now) == 4 * 3600
