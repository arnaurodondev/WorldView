"""Unit tests for the EODHD bulk-EOD once-daily producer (DAILY-VOLUME CORRECTION).

Covers the pure, I/O-free helpers plus the end-to-end canonicalization of a bulk
record — proving a produced daily bar carries the CORRECT consolidated volume +
adjusted_close and the authoritative ``eodhd_bulk`` source (priority 120 in S3).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.scripts.bulk_eod_daily import (
    RunBudget,
    build_symbol_fetch_result,
    covered_symbols_by_exchange,
    index_bulk_records,
    match_record,
    parse_exchanges,
    record_date_range,
)

pytestmark = pytest.mark.unit


# A live-verified bulk record shape.
_AAPL = {
    "code": "AAPL",
    "exchange_short_name": "US",
    "date": "2026-07-16",
    "open": 328.0,
    "high": 334.68,
    "low": 326.79,
    "close": 333.26,
    "adjusted_close": 333.26,
    "volume": 62673782,
    "prev_close": 327.5,
}
_BRKB = {**_AAPL, "code": "BRK-B", "volume": 3_000_000, "adjusted_close": 400.0, "close": 400.0}


def _policy(symbol: str | None, exchange: str, dataset_type: DatasetType = DatasetType.OHLCV, enabled: bool = True):
    return SimpleNamespace(symbol=symbol, exchange=exchange, dataset_type=dataset_type, is_enabled=enabled)


# ── parse_exchanges ───────────────────────────────────────────────────────────


def test_parse_exchanges_dedupes_and_uppercases():
    assert parse_exchanges("us, INDX ,us,shg") == ["US", "INDX", "SHG"]


def test_parse_exchanges_empty():
    assert parse_exchanges("") == []


# ── covered_symbols_by_exchange ───────────────────────────────────────────────


def test_covered_symbols_groups_by_exchange_ohlcv_only():
    policies = [
        _policy("AAPL", "US"),
        _policy("MSFT", "US"),
        _policy("AAPL", "US"),  # duplicate → collapsed
        _policy("0700", "SHG"),
        _policy("SPY", "US", dataset_type=DatasetType.QUOTES),  # non-OHLCV → skipped
        _policy("DIS", "US", enabled=False),  # disabled → skipped
        _policy(None, "US"),  # wildcard → skipped
    ]
    grouped = covered_symbols_by_exchange(policies)  # type: ignore[arg-type]
    assert grouped == {"US": ["AAPL", "MSFT"], "SHG": ["0700"]}


# ── index_bulk_records / match_record ─────────────────────────────────────────


def test_index_and_match_exact():
    index = index_bulk_records([_AAPL, _BRKB])
    assert match_record(index, "AAPL") is _AAPL


def test_match_record_dot_dash_class_share():
    # EODHD codes class shares with a hyphen (BRK-B); a stored dot form must match.
    index = index_bulk_records([_BRKB])
    assert match_record(index, "BRK.B") is _BRKB
    assert match_record(index, "BRK-B") is _BRKB


def test_match_record_absent_returns_none():
    index = index_bulk_records([_AAPL])
    assert match_record(index, "NVDA") is None


# ── record_date_range ─────────────────────────────────────────────────────────


def test_record_date_range_single_day_window():
    dr = record_date_range(_AAPL)
    assert dr.start == datetime(2026, 7, 16, tzinfo=UTC)
    assert dr.end == datetime(2026, 7, 17, tzinfo=UTC)


def test_record_date_range_missing_date_raises():
    with pytest.raises(ValueError, match="date"):
        record_date_range({"code": "AAPL"})


# ── build_symbol_fetch_result ─────────────────────────────────────────────────


def test_build_symbol_fetch_result_is_eodhd_bulk_single_bar():
    dr = record_date_range(_AAPL)
    result = build_symbol_fetch_result(_AAPL, "AAPL", "US", dr)
    assert result.provider is Provider.EODHD_BULK
    assert result.dataset_type is DatasetType.OHLCV
    assert result.bars_returned == 1
    payload = json.loads(result.raw_data.decode())
    assert isinstance(payload, list) and len(payload) == 1
    assert payload[0]["volume"] == 62673782


def test_produced_bar_canonicalizes_with_correct_volume_and_adjusted_close():
    # End-to-end: the same canonicalizer the live worker uses must emit a bar
    # whose volume + adjusted_close come straight from the bulk record and whose
    # source is the authoritative "eodhd_bulk" label.
    from market_ingestion.application.use_cases.strategies.canonicalize import canonicalize_task
    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.domain.value_objects import Timeframe
    from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer

    dr = record_date_range(_AAPL)
    fetch_result = build_symbol_fetch_result(_AAPL, "AAPL", "US", dr)
    task = IngestionTask.create_ohlcv_task(
        provider=Provider.EODHD_BULK,
        symbol="AAPL",
        timeframe=Timeframe("1d"),
        date_range=dr,
        exchange="US",
    )
    canonical_bytes, row_count = canonicalize_task(task, fetch_result, DefaultCanonicalSerializer())
    assert row_count == 1
    bar = json.loads(canonical_bytes.decode().splitlines()[0])
    assert bar["symbol"] == "AAPL"
    assert bar["volume"] == 62673782  # correct consolidated volume
    assert bar["adjusted_close"] == 333.26  # present (Alpaca daily = None)
    assert bar["source"] == "eodhd_bulk"  # → provider_priority 120 in market-data
    assert bar["timeframe"] == "1d"


# ── RunBudget ─────────────────────────────────────────────────────────────────


def test_run_budget_enforces_both_ceilings():
    budget = RunBudget(max_credits=250, daily_cap=100_000, daily_headroom=5_000)
    assert not budget.run_budget_exhausted(100)
    budget.record_exchange()  # +100
    budget.record_exchange()  # +200
    assert budget.spent == 200
    # A third exchange (+100 → 300) would exceed the 250 per-run cap.
    assert budget.run_budget_exhausted(100)
    # Daily headroom: 100_000 - 5_000 = 95_000 usable.
    assert budget.daily_budget_exhausted(daily_used=94_950, next_estimate=100)
    assert not budget.daily_budget_exhausted(daily_used=90_000, next_estimate=100)
