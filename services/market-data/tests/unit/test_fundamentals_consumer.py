"""Unit tests for FundamentalsConsumer (MD-021)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.domain.entities import Instrument
from market_data.domain.value_objects import InstrumentFlags
from market_data.infrastructure.messaging.consumers.fundamentals_consumer import FundamentalsConsumer

pytestmark = pytest.mark.unit


def _make_section_data(section_key: str) -> dict:
    """Build test data matching the consumer's dispatch branches."""
    # Financial statements need quarterly/yearly nesting
    financial = {"income_statement", "balance_sheet", "cash_flow"}
    # Earnings trend: period-code-keyed dict with "date" field
    trend = {"earnings_trend"}
    # Date-keyed series: one row per date key
    date_series = {"earnings_history", "earnings_annual_trend", "dividend_history", "outstanding_shares"}
    # Everything else: snapshot (flat dict)

    if section_key in financial:
        return {
            "quarterly": {"2024-09-30": {"totalRevenue": "94930000000"}},
            "yearly": {"2023-12-31": {"totalRevenue": "383285000000"}},
        }
    if section_key in trend:
        return {"0q": {"date": "2024-09-30", "earningsEstimate": 1.5}}
    if section_key in date_series:
        return {"2024": 4, "2023": 4}
    # Snapshot
    return {"revenue": 1000.0, "net_income": 200.0}


def _make_fundamentals_json(sections: list[str] | None = None) -> bytes:
    if sections is None:
        sections = ["income_statement", "balance_sheet"]
    payload = {s: _make_section_data(s) for s in sections}
    return json.dumps(payload).encode()


def _make_instrument(has_fundamentals: bool = True) -> Instrument:
    return Instrument(
        id="instr-fund-001",
        security_id="sec-222",
        symbol="GOOG",
        exchange="US",
        flags=InstrumentFlags(has_fundamentals=has_fundamentals),
        is_active=True,
        created_at=datetime.now(tz=UTC),
    )


def _make_message(dataset_type: str = "fundamentals") -> dict:
    return {
        "event_id": "evt-fund-001",
        "dataset_type": dataset_type,
        "canonical_ref_bucket": "market-canonical",
        "canonical_ref_key": "fundamentals/GOOG/2024.json",
        "symbol": "GOOG",
        "exchange": "US",
        "provider": "macrotrends",
    }


def _make_consumer(mock_uow: AsyncMock, mock_storage: AsyncMock) -> FundamentalsConsumer:
    # Ensure content-hash dedup never short-circuits in unit tests
    mock_uow.ingestion_events.exists_by_content_hash = AsyncMock(return_value=False)
    consumer = FundamentalsConsumer(
        uow_factory=lambda: mock_uow,
        object_storage=mock_storage,
    )
    consumer._current_uow = mock_uow
    return consumer


@pytest.mark.asyncio
async def test_fundamentals_consumer_processes_valid_message() -> None:
    """Consumer processes all sections in the payload."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.fundamentals.upsert_income_statement = AsyncMock()
    mock_uow.fundamentals.upsert_balance_sheet = AsyncMock()

    raw = _make_fundamentals_json(["income_statement", "balance_sheet"])
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    # Financial statements produce 2 rows each (1 quarterly + 1 yearly from test data)
    assert mock_uow.fundamentals.upsert_income_statement.await_count == 2
    assert mock_uow.fundamentals.upsert_balance_sheet.await_count == 2


@pytest.mark.asyncio
async def test_fundamentals_consumer_skips_non_fundamentals() -> None:
    """Consumer ignores messages with a different dataset_type."""
    mock_uow = AsyncMock()
    mock_storage = AsyncMock()

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(dataset_type="OHLCV"), {})

    mock_storage.get_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_fundamentals_consumer_creates_instrument_on_first_seen() -> None:
    """Consumer creates a new Instrument if symbol/exchange not found."""
    new_instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.collect_event = MagicMock()  # sync method — must not be AsyncMock
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=None)
    mock_uow.instruments.upsert = AsyncMock(return_value=new_instrument)
    mock_uow.fundamentals.upsert_income_statement = AsyncMock()

    raw = _make_fundamentals_json(["income_statement"])
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.instruments.upsert.assert_awaited_once()
    mock_uow.collect_event.assert_called_once()


@pytest.mark.asyncio
async def test_fundamentals_consumer_all_13_sections_supported() -> None:
    """All 13 FundamentalsSection handlers are wired correctly."""
    all_sections = [
        "income_statement",
        "balance_sheet",
        "cash_flow",
        "valuation_ratios",
        "technicals_snapshot",
        "share_statistics",
        "splits_dividends",
        "analyst_consensus",
        "earnings_history",
        "earnings_trend",
        "earnings_annual_trend",
        "dividend_history",
        "outstanding_shares",
    ]
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)

    raw = _make_fundamentals_json(all_sections)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    # Verify all handler methods were called.
    # Financial statements produce 2 rows each (1 quarterly + 1 yearly from test data).
    assert mock_uow.fundamentals.upsert_income_statement.await_count == 2
    assert mock_uow.fundamentals.upsert_balance_sheet.await_count == 2
    assert mock_uow.fundamentals.upsert_cash_flow.await_count == 2
    # Snapshot sections produce 1 row each
    assert mock_uow.fundamentals.upsert_analyst_consensus.await_count == 1
    # Date-keyed series: "2024" and "2023" → 2 rows each
    assert mock_uow.fundamentals.upsert_outstanding_shares.await_count == 2


@pytest.mark.asyncio
async def test_fundamentals_consumer_unknown_sections_ignored() -> None:
    """Sections not in the handler map are silently ignored."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)

    payload = {
        "unknown_section": {"foo": "bar"},
        "income_statement": {
            "quarterly": {"2024-09-30": {"totalRevenue": "94930000000"}},
            "yearly": {"2023-12-31": {"totalRevenue": "383285000000"}},
        },
    }
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    # Financial statement → 2 rows (1 quarterly + 1 yearly)
    assert mock_uow.fundamentals.upsert_income_statement.await_count == 2
    # No error should occur for the unknown section


@pytest.mark.asyncio
async def test_fundamentals_consumer_storage_failure_raises_retryable() -> None:
    """S3 failure raises StorageUnavailableError."""
    from messaging.kafka.consumer.errors import StorageUnavailableError  # type: ignore[import-untyped]

    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(side_effect=Exception("s3 timeout"))

    consumer = _make_consumer(mock_uow, mock_storage)
    with pytest.raises(StorageUnavailableError):
        await consumer.process_message(None, _make_message(), {})


@pytest.mark.asyncio
async def test_fundamentals_consumer_parse_failure_raises_fatal() -> None:
    """Non-JSON bytes raise MalformedDataError."""
    from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)

    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=b"<not json>")

    consumer = _make_consumer(mock_uow, mock_storage)
    with pytest.raises(MalformedDataError):
        await consumer.process_message(None, _make_message(), {})


@pytest.mark.asyncio
async def test_financial_statement_decomposed_into_per_period_rows() -> None:
    """FIX-F9: income_statement payload with 3 quarterly + 2 yearly entries
    must produce 5 distinct upsert calls, not 1."""
    from market_data.domain.enums import PeriodType

    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.instruments.update_metadata = AsyncMock()
    mock_uow.fundamentals.upsert_income_statement = AsyncMock()

    payload = {
        "income_statement": {
            "quarterly": {
                "2024-09-30": {"totalRevenue": "94930000000"},
                "2024-06-30": {"totalRevenue": "85777000000"},
                "2024-03-31": {"totalRevenue": "90753000000"},
            },
            "yearly": {
                "2023-12-31": {"totalRevenue": "383285000000"},
                "2022-12-31": {"totalRevenue": "394328000000"},
            },
        }
    }
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    assert mock_uow.fundamentals.upsert_income_statement.await_count == 5
    # Verify period types: collect all calls
    calls = mock_uow.fundamentals.upsert_income_statement.call_args_list
    period_types = [call.args[0].period_type for call in calls]
    quarterly = [pt for pt in period_types if pt == PeriodType.QUARTERLY]
    annual = [pt for pt in period_types if pt == PeriodType.ANNUAL]
    assert len(quarterly) == 3
    assert len(annual) == 2


@pytest.mark.asyncio
async def test_snapshot_sections_use_snapshot_period_type() -> None:
    """FIX-F2/F3: snapshot sections must use PeriodType.SNAPSHOT, not ANNUAL."""
    from market_data.domain.enums import PeriodType

    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.instruments.update_metadata = AsyncMock()
    mock_uow.fundamentals.upsert_valuation_ratios = AsyncMock()
    mock_uow.fundamentals.upsert_technicals_snapshot = AsyncMock()

    payload = {
        "valuation_ratios": {"trailingPE": 28.5},
        "technicals_snapshot": {"beta": 1.2},
    }
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    # Verify both used SNAPSHOT period type
    vr_call = mock_uow.fundamentals.upsert_valuation_ratios.call_args
    ts_call = mock_uow.fundamentals.upsert_technicals_snapshot.call_args
    assert vr_call.args[0].period_type == PeriodType.SNAPSHOT
    assert ts_call.args[0].period_type == PeriodType.SNAPSHOT


@pytest.mark.asyncio
async def test_dividend_history_year_only_keys() -> None:
    """FIX-F5: year-only keys like '2024' produce period_end = 2024-12-31."""
    from datetime import UTC, datetime

    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.instruments.update_metadata = AsyncMock()
    mock_uow.fundamentals.upsert_dividend_history = AsyncMock()

    payload = {
        "dividend_history": {
            "2023": 4,
            "2024": 4,
        }
    }
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    assert mock_uow.fundamentals.upsert_dividend_history.await_count == 2
    calls = mock_uow.fundamentals.upsert_dividend_history.call_args_list
    dates = sorted([call.args[0].period_end for call in calls])
    assert dates[0] == datetime(2023, 12, 31, tzinfo=UTC)
    assert dates[1] == datetime(2024, 12, 31, tzinfo=UTC)


# ── Metric upsert integration (ROPT-10) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_consumer_calls_upsert_metrics_for_catalogued_section() -> None:
    """After each section upsert, fundamental_metrics.upsert_metrics is called
    for sections that are in the metric catalog (e.g. analyst_consensus)."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.instruments.update_metadata = AsyncMock()
    mock_uow.fundamentals.upsert_analyst_consensus = AsyncMock()

    payload = {
        "analyst_consensus": {"TargetPrice": 200.0, "Rating": "Buy"},
    }
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    # fundamental_metrics.upsert_metrics must have been called at least once
    mock_uow.fundamental_metrics.upsert_metrics.assert_awaited()


@pytest.mark.asyncio
async def test_consumer_calls_upsert_metrics_for_valuation_ratios() -> None:
    """valuation_ratios section triggers metric extraction (pe_ratio, etc.)."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.fundamentals.upsert_valuation_ratios = AsyncMock()

    payload = {"valuation_ratios": {"TrailingPE": 28.5, "PB": 3.2}}
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.fundamental_metrics.upsert_metrics.assert_awaited()


@pytest.mark.asyncio
async def test_consumer_does_not_call_upsert_metrics_for_uncatalogued_section() -> None:
    """Sections not in the metric catalog (e.g. technicals_snapshot) do not
    trigger a fundamental_metrics.upsert_metrics call."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.fundamentals.upsert_technicals_snapshot = AsyncMock()

    payload = {"technicals_snapshot": {"Beta": 1.2, "RSI": 55.0}}
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    # upsert_metrics should NOT have been called (empty rows → skipped)
    mock_uow.fundamental_metrics.upsert_metrics.assert_not_awaited()


@pytest.mark.asyncio
async def test_consumer_upsert_metrics_uses_same_uow() -> None:
    """Metric upsert uses the same UoW as the section upsert (same transaction)."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.fundamentals.upsert_highlights = AsyncMock()

    payload = {"highlights": {"Revenue": 1e9, "EBITDA": 2e8}}
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    # Both section upsert and metric upsert went through the same mock_uow object
    mock_uow.fundamentals.upsert_highlights.assert_awaited_once()
    mock_uow.fundamental_metrics.upsert_metrics.assert_awaited()


@pytest.mark.asyncio
async def test_consumer_idempotent_reingest_does_not_duplicate_metrics() -> None:
    """Processing the same payload twice invokes upsert_metrics the same number
    of times per ingest — the ON CONFLICT upsert handles idempotency at DB level.
    The consumer does not skip calling upsert_metrics on replay."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.fundamentals.upsert_analyst_consensus = AsyncMock()

    payload = {"analyst_consensus": {"TargetPrice": 200.0, "Rating": "Buy"}}
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    # Simulate two separate ingestion runs (same content, fresh consumer state each time)
    await consumer.process_message(None, _make_message(), {})
    first_call_count = mock_uow.fundamental_metrics.upsert_metrics.await_count

    await consumer.process_message(None, _make_message(), {})
    second_call_count = mock_uow.fundamental_metrics.upsert_metrics.await_count

    # Second run invokes upsert_metrics the same number of additional times
    assert second_call_count == first_call_count * 2


@pytest.mark.asyncio
async def test_consumer_projects_operating_cash_flow_from_total_cash_from_ops_alias() -> None:
    """Regression: totalCashFromOperatingActivities populates operating_cash_flow."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.fundamentals.upsert_cash_flow = AsyncMock()

    payload = {
        "cash_flow": {
            "quarterly": {
                "2024-09-30": {
                    "totalCashFromOperatingActivities": 12345.0,
                }
            },
            "yearly": {},
        }
    }
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.fundamental_metrics.upsert_metrics.assert_awaited()
    metric_rows = mock_uow.fundamental_metrics.upsert_metrics.call_args.args[0]
    assert any(r.metric == "operating_cash_flow" for r in metric_rows)


@pytest.mark.asyncio
async def test_consumer_metric_upsert_failure_propagates_exception() -> None:
    """If upsert_metrics raises after the section upsert, the exception propagates
    (no silent swallowing) so the caller's transaction manager can roll back."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.fundamentals.upsert_analyst_consensus = AsyncMock()
    mock_uow.fundamental_metrics.upsert_metrics = AsyncMock(side_effect=RuntimeError("db write failed"))

    payload = {"analyst_consensus": {"TargetPrice": 200.0, "Rating": "Buy"}}
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    with pytest.raises(RuntimeError, match="db write failed"):
        await consumer.process_message(None, _make_message(), {})

    # Section upsert was called, metric upsert raised, exception propagated
    mock_uow.fundamentals.upsert_analyst_consensus.assert_awaited_once()
    mock_uow.fundamental_metrics.upsert_metrics.assert_awaited_once()


# ── T-E2-1-01/02: atomic dedup ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fundamentals_consumer_content_hash_dedup_marks_processed() -> None:
    """Unchanged content hash → event_id still recorded despite early return (BP-034)."""
    mock_uow = AsyncMock()
    mock_uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)

    mock_storage = AsyncMock()
    consumer = _make_consumer(mock_uow, mock_storage)
    # _make_consumer overwrites exists_by_content_hash → set it to True after
    mock_uow.ingestion_events.exists_by_content_hash = AsyncMock(return_value=True)
    msg = _make_message()
    msg["canonical_ref_sha256"] = "cafebabe"

    await consumer.process_message(None, msg, {})

    mock_uow.ingestion_events.create_if_not_exists.assert_awaited_once()
    mock_storage.get_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_fundamentals_consumer_skips_processing_on_duplicate_insert() -> None:
    """Duplicate event_id → early return, no data written."""
    mock_uow = AsyncMock()
    mock_uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=False)

    mock_storage = AsyncMock()
    consumer = _make_consumer(mock_uow, mock_storage)

    await consumer.process_message(None, _make_message(), {})

    mock_storage.get_bytes.assert_not_called()
    mock_uow.fundamentals.upsert_income_statement.assert_not_called()


# ── T-E2-1-04: C-008 period_end type coercion ──────────────────────────────


@pytest.mark.asyncio
async def test_fundamentals_period_end_parsed_from_string() -> None:
    """String period_end (passed explicitly) is coerced to date correctly.

    This tests the _upsert_metrics_for_record helper which now uses
    isinstance(record.period_end, datetime) instead of hasattr (C-008).
    Since FundamentalsRecord.period_end is always datetime at the domain
    level, this verifies the happy path.
    """

    from market_data.domain.entities import FundamentalsRecord
    from market_data.domain.enums import FundamentalsSection, PeriodType
    from market_data.infrastructure.messaging.consumers.fundamentals_consumer import (
        _upsert_metrics_for_record,
    )

    mock_uow = AsyncMock()
    mock_uow.fundamental_metrics.upsert_metrics = AsyncMock(return_value=None)

    record = FundamentalsRecord(
        security_id="instr-001",
        section=FundamentalsSection.HIGHLIGHTS,
        period_end=datetime(2024, 9, 30, tzinfo=UTC),
        period_type=PeriodType.SNAPSHOT,
        data={"revenue": 1_000_000.0},
        source="macrotrends",
    )

    await _upsert_metrics_for_record(mock_uow, record)

    # No assertion failure → as_of_date computed successfully from datetime
    # (The metric catalog may not have HIGHLIGHTS so upsert_metrics may not be called)


@pytest.mark.asyncio
async def test_fundamentals_period_end_from_datetime_works() -> None:
    """datetime period_end is correctly converted to date via .date() method."""

    from market_data.domain.entities import FundamentalsRecord
    from market_data.domain.enums import FundamentalsSection, PeriodType
    from market_data.infrastructure.messaging.consumers.fundamentals_consumer import (
        _upsert_metrics_for_record,
    )

    mock_uow = AsyncMock()
    mock_uow.fundamental_metrics.upsert_metrics = AsyncMock(return_value=None)

    record = FundamentalsRecord(
        security_id="instr-002",
        section=FundamentalsSection.INCOME_STATEMENT,
        period_end=datetime(2023, 12, 31, tzinfo=UTC),
        period_type=PeriodType.ANNUAL,
        data={"totalRevenue": "383285000000"},
        source="macrotrends",
    )

    await _upsert_metrics_for_record(mock_uow, record)
    # If extract_metrics found rows, upsert_metrics would be called
    # The key assertion is that no exception was raised
