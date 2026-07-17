"""Unit tests for the once-daily post-close EODHD 1m intraday refinement.

Covers the pure, I/O-free helpers (day resolution, weekend guard, UTC-day window,
resume-set key, credit budget, source re-stamping) plus the end-to-end
canonicalization of an EODHD ``/intraday`` record — proving a produced 1m bar
carries the CORRECT consolidated volume, a UTC bar-start ``date`` that ALIGNS with
Alpaca's 1m convention, and the authoritative ``eodhd_intraday`` source (which S3
resolves to priority 115 — above Alpaca's IEX 1m at 110).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from market_ingestion.application.ports.adapters import ProviderFetchResult
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.scripts.intraday_refine import (
    _CREDITS_PER_SYMBOL,
    RunBudget,
    day_date_range,
    day_unix_window,
    done_set_key,
    is_weekend,
    resolve_target_day,
    stamp_intraday_source,
)

pytestmark = pytest.mark.unit


# A live-verified EODHD /intraday 1m record shape (UTC bar-start, consolidated vol).
# 2026-07-15 13:30:00 UTC = 09:30 ET regular-session open.
_BAR_1330 = {
    "timestamp": 1752586200,
    "gmtoffset": 0,
    "datetime": "2026-07-15 13:30:00",
    "open": 100.0,
    "high": 101.0,
    "low": 99.5,
    "close": 100.5,
    "volume": 3_930_530,
}


# ── resolve_target_day ────────────────────────────────────────────────────────


def test_resolve_target_day_explicit_is_utc_midnight():
    day = resolve_target_day("2026-07-15")
    assert day == datetime(2026, 7, 15, tzinfo=UTC)


def test_resolve_target_day_default_is_today_utc():
    day = resolve_target_day(None)
    now = datetime.now(tz=UTC)
    assert (day.year, day.month, day.day) == (now.year, now.month, now.day)
    assert day.hour == 0 and day.tzinfo == UTC


def test_resolve_target_day_bad_format_raises():
    with pytest.raises(ValueError):
        resolve_target_day("07/15/2026")


# ── is_weekend ────────────────────────────────────────────────────────────────


def test_is_weekend_true_for_saturday_sunday():
    assert is_weekend(resolve_target_day("2026-07-18"))  # Saturday
    assert is_weekend(resolve_target_day("2026-07-19"))  # Sunday


def test_is_weekend_false_for_weekday():
    assert not is_weekend(resolve_target_day("2026-07-15"))  # Wednesday


# ── day_unix_window / day_date_range ──────────────────────────────────────────


def test_day_unix_window_covers_full_utc_calendar_day():
    from_ts, to_ts = day_unix_window(resolve_target_day("2026-07-15"))
    assert from_ts == int(datetime(2026, 7, 15, tzinfo=UTC).timestamp())
    assert to_ts == int(datetime(2026, 7, 16, tzinfo=UTC).timestamp())
    # 24h window bracketing pre-market, regular, and after-hours (all in UTC).
    assert (to_ts - from_ts) == 24 * 60 * 60


def test_day_date_range_single_day_window():
    dr = day_date_range(resolve_target_day("2026-07-15"))
    assert dr.start == datetime(2026, 7, 15, tzinfo=UTC)
    assert dr.end == datetime(2026, 7, 16, tzinfo=UTC)


# ── done_set_key ──────────────────────────────────────────────────────────────


def test_done_set_key_is_per_day_and_versioned():
    assert done_set_key(resolve_target_day("2026-07-15")) == "s2:v1:intraday_refine:2026-07-15:done"


# ── stamp_intraday_source ─────────────────────────────────────────────────────


def test_stamp_intraday_source_overrides_provider_only():
    raw = ProviderFetchResult(
        provider=Provider.EODHD,  # adapter default
        dataset_type=DatasetType.OHLCV,
        symbol="AAPL",
        raw_data=json.dumps([_BAR_1330]).encode(),
        content_type="application/json",
        fetched_at=datetime.now(tz=UTC),
        duration_ms=7,
        bars_returned=1,
    )
    stamped = stamp_intraday_source(raw)
    # Only the source identity flips — everything else is preserved verbatim.
    assert stamped.provider is Provider.EODHD_INTRADAY
    assert stamped.raw_data == raw.raw_data
    assert stamped.bars_returned == 1
    assert raw.provider is Provider.EODHD  # original untouched (pure)


# ── RunBudget ─────────────────────────────────────────────────────────────────


def test_credits_per_symbol_is_five():
    # EODHD /intraday costs 5 credits/request regardless of interval.
    assert _CREDITS_PER_SYMBOL == 5


def test_run_budget_enforces_both_ceilings():
    budget = RunBudget(max_credits=12, daily_cap=100_000, daily_headroom=5_000)
    assert not budget.run_budget_exhausted(5)
    budget.record_symbol()  # +5
    budget.record_symbol()  # +10
    assert budget.spent == 10
    # A third symbol (+5 → 15) would exceed the 12 per-run cap.
    assert budget.run_budget_exhausted(5)
    # Daily headroom: 100_000 - 5_000 = 95_000 usable.
    assert budget.daily_budget_exhausted(daily_used=94_996, next_estimate=5)
    assert not budget.daily_budget_exhausted(daily_used=90_000, next_estimate=5)


def test_full_us_sweep_credit_estimate_fits_daily_cap():
    # 530 covered US equities x 5 credits = 2,650/sweep — plus daily bulk EOD
    # (~543) + the existing firehose (~1.1k) is ~4.3k, well under the 100k/day cap.
    assert 530 * _CREDITS_PER_SYMBOL == 2_650
    assert 2_650 + 543 + 1_100 < 100_000


# ── end-to-end canonicalization ───────────────────────────────────────────────


def test_produced_1m_bar_canonicalizes_with_consolidated_volume_and_aligned_ts():
    # The same canonicalizer the live worker uses must emit a 1m bar whose volume
    # is the consolidated CTA/UTP figure (not IEX), whose ``date`` is the UTC
    # bar-start minute (aligns with Alpaca's 1m bar_date so the S3 upsert guard
    # REPLACES the IEX bar), and whose source is the authoritative eodhd_intraday.
    from market_ingestion.application.use_cases.strategies.canonicalize import canonicalize_task
    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.domain.value_objects import Timeframe
    from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer

    dr = day_date_range(resolve_target_day("2026-07-15"))
    raw = ProviderFetchResult(
        provider=Provider.EODHD,
        dataset_type=DatasetType.OHLCV,
        symbol="AAPL",
        raw_data=json.dumps([_BAR_1330]).encode(),
        content_type="application/json",
        fetched_at=datetime.now(tz=UTC),
        duration_ms=7,
        bars_returned=1,
    )
    fetch_result = stamp_intraday_source(raw)
    task = IngestionTask.create_ohlcv_task(
        provider=Provider.EODHD_INTRADAY,
        symbol="AAPL",
        timeframe=Timeframe("1m"),
        date_range=dr,
        exchange="US",
    )
    canonical_bytes, row_count = canonicalize_task(task, fetch_result, DefaultCanonicalSerializer())
    assert row_count == 1
    bar = json.loads(canonical_bytes.decode().splitlines()[0])
    assert bar["symbol"] == "AAPL"
    assert bar["volume"] == 3_930_530  # consolidated, NOT the ~5% IEX figure
    assert bar["source"] == "eodhd_intraday"  # → provider_priority 115 in market-data
    # UTC bar-start minute — the exact-minute alignment that makes it collide with
    # (and supersede) the Alpaca IEX 1m bar rather than duplicate it.
    assert bar["date"].startswith("2026-07-15T13:30:00")
