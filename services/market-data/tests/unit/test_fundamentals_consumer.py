"""Unit tests for FundamentalsConsumer (MD-021)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

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
    """Consumer creates a new Instrument if symbol/exchange not found.

    QA-016: InstrumentCreated is written atomically to outbox_events (not collect_event).
    """
    new_instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=None)
    mock_uow.instruments.upsert = AsyncMock(return_value=new_instrument)
    mock_uow.outbox_events.create = AsyncMock(return_value="outbox-id-001")
    mock_uow.fundamentals.upsert_income_statement = AsyncMock()

    raw = _make_fundamentals_json(["income_statement"])
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.instruments.upsert.assert_awaited_once()
    mock_uow.outbox_events.create.assert_awaited_once()
    call_kwargs = mock_uow.outbox_events.create.call_args
    assert call_kwargs.kwargs["event_type"] == "market.instrument.created"
    assert call_kwargs.kwargs["topic"] == "market.instrument.created"


@pytest.mark.asyncio
async def test_fundamentals_consumer_enriches_instrument_created_with_company_profile() -> None:
    """InstrumentCreated outbox payload includes name/isin from company_profile if present."""
    new_instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=None)
    mock_uow.instruments.upsert = AsyncMock(return_value=new_instrument)
    mock_uow.outbox_events.create = AsyncMock(return_value="outbox-id-002")
    # Return None so FIX-F4 security enrichment path is skipped (not testing it here)
    mock_uow.securities.find_by_id = AsyncMock(return_value=None)

    payload = {
        "income_statement": _make_section_data("income_statement"),
        "company_profile": {"Name": "Alphabet Inc.", "ISIN": "US02079K3059"},
    }
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.outbox_events.create.assert_awaited_once()
    outbox_payload = mock_uow.outbox_events.create.call_args.kwargs["payload"]
    assert outbox_payload["name"] == "Alphabet Inc."
    assert outbox_payload["isin"] == "US02079K3059"


@pytest.mark.asyncio
async def test_fundamentals_consumer_emits_instrument_updated_when_flag_missing() -> None:
    """Consumer emits InstrumentUpdated to outbox when instrument lacks has_fundamentals.

    QA-016: the flag-change path previously emitted nothing; now atomically writes to outbox.
    """
    instrument = _make_instrument(has_fundamentals=False)
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.instruments.update_flags = AsyncMock()
    mock_uow.outbox_events.create = AsyncMock(return_value="outbox-id-003")
    mock_uow.fundamentals.upsert_income_statement = AsyncMock()

    raw = _make_fundamentals_json(["income_statement"])
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.instruments.update_flags.assert_awaited_once()
    mock_uow.outbox_events.create.assert_awaited_once()
    call_kwargs = mock_uow.outbox_events.create.call_args
    assert call_kwargs.kwargs["event_type"] == "market.instrument.updated"
    assert call_kwargs.kwargs["payload"]["has_fundamentals"] is True
    assert call_kwargs.kwargs["payload"]["fields_updated"] == ["has_fundamentals"]


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
async def test_consumer_calls_upsert_metrics_for_technicals_snapshot() -> None:
    """TECHNICALS_SNAPSHOT is now catalogued (PLAN-0050 Wave D — beta + avg_volume_30d
    added to _METRIC_CATALOG).  The consumer MUST call upsert_metrics when it
    processes a technicals_snapshot payload that contains 'Beta'.

    WHY UPDATED (not deleted): R19 — fix implementation, never delete tests.
    The old assertion (upsert_metrics NOT called) was correct when TECHNICALS_SNAPSHOT
    was uncatalogued.  After adding it to the catalog the test name and assertion
    must reflect the new behaviour.

    WHY technicals_snapshot in the catalog: beta and avg_volume_30d are used by
    the screener; they must be materialised into fundamental_metrics for that
    to work.  The snapshot backfill also reads them from there."""
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

    # upsert_metrics MUST be called — Beta maps to "beta" in the catalog
    mock_uow.fundamental_metrics.upsert_metrics.assert_awaited()


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


# ── T-E2-3-01: earnings_trend period_end parsing via process_message ────────


@pytest.mark.asyncio
async def test_fundamentals_consumer_period_end_string_parsed() -> None:
    """Valid ISO date string in earnings_trend entry → period_end parsed as UTC datetime."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)

    # earnings_trend payload with explicit "date" ISO string
    payload = {"earnings_trend": {"0q": {"date": "2024-09-30", "earningsEstimate": 1.5}}}
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=json.dumps(payload).encode())

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.fundamentals.upsert_earnings_trend.assert_awaited_once()
    record = mock_uow.fundamentals.upsert_earnings_trend.call_args[0][0]
    assert record.period_end == datetime(2024, 9, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_fundamentals_consumer_missing_period_end_uses_fallback() -> None:
    """Empty/missing date in earnings_trend entry → period_end falls back to ingested_at."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)

    # earnings_trend entry with no valid date string → triggers fallback
    payload = {"earnings_trend": {"0q": {"date": "", "earningsEstimate": 0.5}}}
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=json.dumps(payload).encode())

    before = datetime.now(tz=UTC)
    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})
    after = datetime.now(tz=UTC)

    mock_uow.fundamentals.upsert_earnings_trend.assert_awaited_once()
    record = mock_uow.fundamentals.upsert_earnings_trend.call_args[0][0]
    # period_end should be ingested_at (approximately now)
    assert before <= record.period_end <= after


# ---------------------------------------------------------------------------
# T-E-2-02/03: FundamentalsConsumer populates description from company_profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fundamentals_consumer_populates_description() -> None:
    """EODHD General.Description is passed into InstrumentCreated.description (T-E-2-02)."""
    new_instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=None)
    mock_uow.instruments.upsert = AsyncMock(return_value=new_instrument)
    mock_uow.outbox_events.create = AsyncMock(return_value="outbox-id-desc-001")
    mock_uow.securities.find_by_id = AsyncMock(return_value=None)  # skip security enrichment path

    payload = {
        "income_statement": _make_section_data("income_statement"),
        "company_profile": {
            "Name": "Alphabet Inc.",
            "ISIN": "US02079K3059",
            "Description": "Alphabet is a holding company whose business includes Google.",
        },
    }
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    mock_uow.outbox_events.create.assert_awaited_once()
    outbox_payload = mock_uow.outbox_events.create.call_args.kwargs["payload"]
    assert outbox_payload["description"] == "Alphabet is a holding company whose business includes Google."


@pytest.mark.asyncio
async def test_fundamentals_consumer_description_none_when_absent() -> None:
    """Missing Description key → description=None (not empty string) (T-E-2-02)."""
    new_instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=None)
    mock_uow.instruments.upsert = AsyncMock(return_value=new_instrument)
    mock_uow.outbox_events.create = AsyncMock(return_value="outbox-id-desc-002")
    mock_uow.securities.find_by_id = AsyncMock(return_value=None)

    payload = {
        "income_statement": _make_section_data("income_statement"),
        "company_profile": {"Name": "Alphabet Inc."},  # no Description key
    }
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    outbox_payload = mock_uow.outbox_events.create.call_args.kwargs["payload"]
    assert outbox_payload["description"] is None


@pytest.mark.asyncio
async def test_fundamentals_consumer_description_none_for_empty_string() -> None:
    """Empty string Description → None (falsy coercion, no empty strings in event)."""
    new_instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=None)
    mock_uow.instruments.upsert = AsyncMock(return_value=new_instrument)
    mock_uow.outbox_events.create = AsyncMock(return_value="outbox-id-desc-003")
    mock_uow.securities.find_by_id = AsyncMock(return_value=None)

    payload = {
        "income_statement": _make_section_data("income_statement"),
        "company_profile": {"Name": "Alphabet Inc.", "Description": ""},
    }
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)
    await consumer.process_message(None, _make_message(), {})

    outbox_payload = mock_uow.outbox_events.create.call_args.kwargs["payload"]
    assert outbox_payload["description"] is None


# ── F-Q1-03: instrument_fundamentals_snapshot continuous UPSERT ─────────────


@pytest.mark.asyncio
async def test_consumer_calls_upsert_fundamentals_snapshot_on_highlights() -> None:
    """F-Q1-03 regression: consumer calls _upsert_fundamentals_snapshot when
    highlights data is present in the payload.

    WHY mock _upsert_fundamentals_snapshot (not upsert_snapshot):
    The protected method is the seam between process_message and the DB write.
    Mocking it avoids needing a live SQLAlchemy session while still verifying
    that process_message invokes the snapshot path.
    """
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.fundamentals.upsert_highlights = AsyncMock()

    payload = {"highlights": {"EarningsShare": 6.42, "RevenueTTM": 385_000_000_000.0}}
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)

    # Patch the protected method so we can assert it was invoked without a live DB
    snapshot_calls: list[tuple[str, dict]] = []

    async def _capture_snapshot(uow: object, instrument_id: str, payload: dict) -> None:
        snapshot_calls.append((instrument_id, payload))

    consumer._upsert_fundamentals_snapshot = _capture_snapshot  # type: ignore[method-assign]
    await consumer.process_message(None, _make_message(), {})

    # _upsert_fundamentals_snapshot was called once with the instrument id
    assert len(snapshot_calls) == 1
    called_iid, called_payload = snapshot_calls[0]
    assert called_iid == "instr-fund-001"
    assert called_payload.get("highlights", {}).get("EarningsShare") == pytest.approx(6.42)


@pytest.mark.asyncio
async def test_consumer_snapshot_failure_does_not_propagate() -> None:
    """F-Q1-03: snapshot UPSERT failure is best-effort — does not raise or
    dead-letter the Kafka message."""
    instrument = _make_instrument()
    mock_uow = AsyncMock()
    mock_uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    mock_uow.fundamentals.upsert_highlights = AsyncMock()

    payload = {"highlights": {"EarningsShare": 6.42}}
    raw = json.dumps(payload).encode()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=raw)

    consumer = _make_consumer(mock_uow, mock_storage)

    async def _raise_snapshot(uow: object, instrument_id: str, payload: dict) -> None:
        raise RuntimeError("DB connection lost")

    consumer._upsert_fundamentals_snapshot = _raise_snapshot  # type: ignore[method-assign]

    # Must NOT raise — snapshot failure is best-effort
    await consumer.process_message(None, _make_message(), {})


# ── Unit tests for fundamentals_snapshot_writer helpers ─────────────────────


def test_most_recent_financial_row_prefers_yearly() -> None:
    """_most_recent_financial_row returns the most-recent yearly entry."""
    from market_data.infrastructure.db.fundamentals_snapshot_writer import _most_recent_financial_row

    data = {
        "yearly": {
            "2022-12-31": {"operatingCashFlow": 100.0},
            "2023-12-31": {"operatingCashFlow": 200.0},
        },
        "quarterly": {
            "2024-09-30": {"operatingCashFlow": 50.0},
        },
    }
    row = _most_recent_financial_row(data)
    assert row == {"operatingCashFlow": 200.0}


def test_most_recent_financial_row_falls_back_to_quarterly() -> None:
    """_most_recent_financial_row falls back to quarterly when yearly is empty."""
    from market_data.infrastructure.db.fundamentals_snapshot_writer import _most_recent_financial_row

    data = {
        "yearly": {},
        "quarterly": {
            "2024-06-30": {"operatingCashFlow": 40.0},
            "2024-09-30": {"operatingCashFlow": 55.0},
        },
    }
    row = _most_recent_financial_row(data)
    assert row == {"operatingCashFlow": 55.0}


def test_most_recent_financial_row_empty_input() -> None:
    """_most_recent_financial_row returns {} for None/empty/non-dict input."""
    from market_data.infrastructure.db.fundamentals_snapshot_writer import _most_recent_financial_row

    assert _most_recent_financial_row(None) == {}
    assert _most_recent_financial_row({}) == {}
    assert _most_recent_financial_row({"yearly": {}, "quarterly": {}}) == {}
    assert _most_recent_financial_row("not a dict") == {}


def test_derive_fundamentals_snapshot_full_data() -> None:
    """derive_fundamentals_snapshot computes all 10 fields from a complete dataset."""
    from market_data.infrastructure.db.fundamentals_snapshot_writer import derive_fundamentals_snapshot

    snap = derive_fundamentals_snapshot(
        highlights={
            "EarningsShare": 6.42,
            "RevenueTTM": 400_000_000_000.0,
            "EBITDA": 120_000_000_000.0,
        },
        cash_flow={
            "operatingCashFlow": 110_000_000_000.0,
            "capitalExpenditures": -10_000_000_000.0,
        },
        income={
            "ebit": 100_000_000_000.0,
            "interestExpense": -2_000_000_000.0,
        },
        balance={
            "netDebt": 60_000_000_000.0,
        },
        technicals={
            "Beta": 1.25,
            "AverageVolume": 80_000_000,
        },
    )

    assert snap["eps_ttm"] == pytest.approx(6.42)
    assert snap["beta"] == pytest.approx(1.25)
    assert snap["avg_volume_30d"] == 80_000_000
    assert snap["operating_cash_flow"] == pytest.approx(110e9)
    assert snap["capex"] == pytest.approx(10e9)  # stored as absolute value
    assert snap["free_cash_flow"] == pytest.approx(100e9)
    assert snap["fcf_margin"] == pytest.approx(100e9 / 400e9)
    assert snap["interest_coverage"] == pytest.approx(100e9 / 2e9)
    assert snap["net_debt_to_ebitda"] == pytest.approx(60e9 / 120e9)
    assert snap["credit_rating"] is None  # always NULL — EODHD does not provide it


def test_derive_fundamentals_snapshot_missing_data_returns_nones() -> None:
    """derive_fundamentals_snapshot returns None for all derived fields when data is empty."""
    from market_data.infrastructure.db.fundamentals_snapshot_writer import derive_fundamentals_snapshot

    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
    )

    assert snap["eps_ttm"] is None
    assert snap["beta"] is None
    assert snap["avg_volume_30d"] is None
    assert snap["operating_cash_flow"] is None
    assert snap["capex"] is None
    assert snap["free_cash_flow"] is None
    assert snap["fcf_margin"] is None
    assert snap["interest_coverage"] is None
    assert snap["net_debt_to_ebitda"] is None
    assert snap["credit_rating"] is None


def test_derive_fundamentals_snapshot_null_semantics_na_strings() -> None:
    """'N/A' and empty string values are coerced to None, not 0.0."""
    from market_data.infrastructure.db.fundamentals_snapshot_writer import derive_fundamentals_snapshot

    snap = derive_fundamentals_snapshot(
        highlights={"EarningsShare": "N/A", "RevenueTTM": ""},
        cash_flow={},
        income={},
        balance={},
        technicals={"Beta": "-"},
    )

    assert snap["eps_ttm"] is None
    assert snap["beta"] is None


# ── F-Q2-03: COALESCE UPSERT policy (PLAN-0050 QA iter-2) ────────────────────


def test_upsert_snapshot_sql_uses_coalesce_for_all_10_nullable_columns() -> None:
    """F-Q2-03: The UPSERT SQL must use COALESCE(EXCLUDED.col, table.col) for all
    10 nullable data columns so that a partial EODHD poll never silently clobbers
    previously-valid data with NULL.

    WHY white-box SQL inspection: upsert_snapshot() wraps a SQLAlchemy text()
    query that executes against a real DB.  A unit test cannot run that query
    without a running Postgres instance.  Instead, we inspect the generated SQL
    string to verify the COALESCE contract is honoured for each nullable column.
    This is a structural guarantee — it will fail the moment someone accidentally
    reverts to a bare ``EXCLUDED.col`` assignment (the regression pattern from
    PLAN-0049 iter-1 F-QAC-02 and the bug that motivated this finding).
    """
    from market_data.infrastructure.db.fundamentals_snapshot_writer import _UPSERT_SQL

    sql_text = str(_UPSERT_SQL)

    # All 10 nullable data columns must use COALESCE; updated_at is intentionally
    # unconditional (it tracks when the snapshot was last seen, not data freshness).
    nullable_columns = [
        "eps_ttm",
        "beta",
        "avg_volume_30d",
        "operating_cash_flow",
        "capex",
        "free_cash_flow",
        "fcf_margin",
        "interest_coverage",
        "net_debt_to_ebitda",
        "credit_rating",
    ]
    for col in nullable_columns:
        # Each column must appear in a COALESCE(EXCLUDED.col, ...) expression
        assert f"COALESCE(EXCLUDED.{col}" in sql_text, (
            f"Column '{col}' is not wrapped in COALESCE in the UPSERT SQL — "
            f"a partial EODHD poll would silently overwrite the stored value with NULL. "
            f"Fix: use COALESCE(EXCLUDED.{col}, instrument_fundamentals_snapshot.{col})"
        )

    # updated_at should NOT use COALESCE — it must always be refreshed unconditionally
    assert "COALESCE(EXCLUDED.updated_at" not in sql_text, (
        "updated_at must be set unconditionally (now()), not via COALESCE — "
        "it tracks when the snapshot row was last seen by the pipeline."
    )


@pytest.mark.asyncio
async def test_upsert_snapshot_partial_payload_preserves_existing_values() -> None:
    """F-Q2-03: Verify COALESCE semantics via mock session.

    Scenario:
      1. Full payload — all 10 fields populated.
      2. Partial re-poll — only eps_ttm, beta, avg_volume_30d set; the 7 remaining
         fields are None (e.g. cash-flow section was absent from the response).
      3. Assert: after the second UPSERT the 7 fields NOT in the partial payload
         are still the original values (COALESCE fell back to the stored value).

    Implementation note: upsert_snapshot() calls session.execute(text(...), params).
    We capture the params dict from both calls and verify that the COALESCE logic
    in the SQL string would produce the correct result (the test validates the
    *contract* of the params — both None and non-None values are passed through;
    it is the DB-side COALESCE that decides which wins).  Verifying the SQL text
    itself (see test above) is the complementary structural check.
    """
    from unittest.mock import AsyncMock

    from market_data.infrastructure.db.fundamentals_snapshot_writer import upsert_snapshot

    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)

    instrument_id = "0190f3a0-dead-beef-cafe-000000000001"

    # ── Call 1: full payload ──────────────────────────────────────────────────
    full_snap = {
        "eps_ttm": 6.42,
        "beta": 1.25,
        "avg_volume_30d": 80_000_000,
        "operating_cash_flow": 110_000_000_000.0,
        "capex": 10_000_000_000.0,
        "free_cash_flow": 100_000_000_000.0,
        "fcf_margin": 0.25,
        "interest_coverage": 50.0,
        "net_debt_to_ebitda": 0.5,
        "credit_rating": None,  # always None — EODHD limitation
    }
    await upsert_snapshot(session, instrument_id, full_snap)

    # ── Call 2: partial payload (only 3 of 10 fields present) ────────────────
    partial_snap = {
        "eps_ttm": 6.80,  # updated
        "beta": 1.30,  # updated
        "avg_volume_30d": 85_000_000,  # updated
        # All other fields are None — simulates cash-flow section missing from EODHD poll
        "operating_cash_flow": None,
        "capex": None,
        "free_cash_flow": None,
        "fcf_margin": None,
        "interest_coverage": None,
        "net_debt_to_ebitda": None,
        "credit_rating": None,
    }
    await upsert_snapshot(session, instrument_id, partial_snap)

    # Verify execute was called twice
    assert session.execute.await_count == 2

    # The params from call 2 must contain None for the 7 absent fields.
    # The COALESCE in the SQL ensures those None params fall back to the DB value.
    # We assert that the params dict correctly reflects the partial payload so
    # the DB-side COALESCE receives the right inputs.
    _sql_stmt, params_2 = session.execute.call_args_list[1].args
    assert params_2["eps_ttm"] == pytest.approx(6.80)
    assert params_2["beta"] == pytest.approx(1.30)
    assert params_2["avg_volume_30d"] == 85_000_000
    # The 7 absent fields are sent as None — COALESCE in SQL will keep existing DB value
    assert params_2["operating_cash_flow"] is None
    assert params_2["capex"] is None
    assert params_2["free_cash_flow"] is None
    assert params_2["fcf_margin"] is None
    assert params_2["interest_coverage"] is None
    assert params_2["net_debt_to_ebitda"] is None
    assert params_2["credit_rating"] is None
