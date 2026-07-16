"""Unit tests for EarningsCalendarConsumer + PgEarningsCalendarRepository.

Covers (fix/data-coverage-warns):
  * pure helpers — ``_parse_code`` / ``_coerce_decimal`` / ``_coerce_date``;
  * ``_build_rows`` — dict payload with an ``earnings`` list, per-row code
    resolution, resolution caching, skip-unknown-instrument, skip-missing
    report_date, numeric/date coercion;
  * ``process_message`` — dataset gate + event-dedup gate;
  * repo ``insert_batch`` SQL shape (ON CONFLICT + COALESCE + UUIDv7 default).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_data.infrastructure.db.repositories.earnings_calendar_repo import (
    PgEarningsCalendarRepository,
)
from market_data.infrastructure.messaging.consumers.earnings_calendar_consumer import (
    EarningsCalendarConsumer,
    _coerce_date,
    _coerce_decimal,
    _parse_code,
)

pytestmark = pytest.mark.unit


# ── _parse_code ─────────────────────────────────────────────────────────────


def test_parse_code_ticker_exchange() -> None:
    """``AAPL.US`` → (``AAPL``, ``US``); suffix passes straight through."""
    assert _parse_code("AAPL.US") == ("AAPL", "US")


def test_parse_code_multiclass_ticker_preserved() -> None:
    """Split on the LAST dot so dot-form multi-class tickers survive.

    EODHD ships ``BRK-B.US``; ``_normalize_ticker`` maps ``BRK-B`` → ``BRK.B``,
    and only the trailing ``.US`` exchange suffix is peeled off.
    """
    assert _parse_code("BRK-B.US") == ("BRK.B", "US")


def test_parse_code_non_us_suffix_passthrough() -> None:
    assert _parse_code("SAP.XETRA") == ("SAP", "XETRA")


def test_parse_code_missing_or_malformed_returns_none() -> None:
    assert _parse_code(None) is None
    assert _parse_code("") is None
    assert _parse_code("NOEXCHANGE") is None  # no dot
    assert _parse_code(42) is None  # type: ignore[arg-type]
    assert _parse_code("AAPL.") is None  # empty suffix


# ── _coerce_decimal / _coerce_date ──────────────────────────────────────────


def test_coerce_decimal_happy_and_nullish() -> None:
    assert _coerce_decimal("2.1") == Decimal("2.1")
    assert _coerce_decimal(3) == Decimal("3")
    assert _coerce_decimal(None) is None
    assert _coerce_decimal("") is None
    assert _coerce_decimal("n/a") is None


def test_coerce_date_happy_and_nullish() -> None:
    assert _coerce_date("2026-02-01") == date(2026, 2, 1)
    assert _coerce_date("2026-02-01T00:00:00") == date(2026, 2, 1)
    assert _coerce_date(None) is None
    assert _coerce_date("") is None
    assert _coerce_date("not-a-date") is None


# ── _build_rows (per-row resolution) ────────────────────────────────────────


def _make_uow(resolver: dict[tuple[str, str], object]) -> AsyncMock:
    """Build a fake UoW whose ``instruments.find_by_symbol_exchange`` looks up
    ``resolver`` keyed by (symbol, exchange). Missing key → None (unknown)."""
    uow = AsyncMock()

    async def _find(symbol: str, exchange: str) -> object | None:
        return resolver.get((symbol, exchange))

    uow.instruments.find_by_symbol_exchange = AsyncMock(side_effect=_find)
    return uow


def _envelope(earnings: object) -> dict[str, object]:
    return {"source": "eodhd", "payload": {"type": "Earnings", "earnings": earnings}}


@pytest.mark.asyncio
async def test_build_rows_resolves_each_row_and_coerces() -> None:
    """Each row's own ``code`` resolves to an instrument; fields are coerced."""
    uow = _make_uow(
        {
            ("AAPL", "US"): SimpleNamespace(id="instr-aapl"),
            ("MSFT", "US"): SimpleNamespace(id="instr-msft"),
        }
    )
    consumer = EarningsCalendarConsumer(uow_factory=lambda: uow, object_storage=None)
    envelope = _envelope(
        [
            {
                "code": "AAPL.US",
                "report_date": "2026-02-01",
                "date": "2025-12-31",
                "before_after_market": "AfterMarket",
                "currency": "USD",
                "estimate": 2.1,
                "actual": None,
            },
            {
                "code": "MSFT.US",
                "report_date": "2026-01-28",
                "date": "2025-12-31",
                "before_after_market": "BeforeMarket",
                "currency": "USD",
                "estimate": "3.05",
                "actual": "3.10",
            },
        ]
    )

    rows = await consumer._build_rows(uow, envelope)

    assert len(rows) == 2
    aapl = rows[0]
    assert aapl["instrument_id"] == "instr-aapl"
    assert aapl["report_date"] == date(2026, 2, 1)
    assert aapl["fiscal_date"] == date(2025, 12, 31)
    assert aapl["eps_estimate"] == Decimal("2.1")
    assert aapl["eps_actual"] is None
    assert aapl["before_after"] == "AfterMarket"
    assert aapl["currency"] == "USD"
    assert "id" in aapl  # UUIDv7 filled by the consumer
    msft = rows[1]
    assert msft["eps_estimate"] == Decimal("3.05")
    assert msft["eps_actual"] == Decimal("3.10")


@pytest.mark.asyncio
async def test_build_rows_skips_unknown_instrument() -> None:
    """Rows whose instrument is not in our universe are skipped (never raised)."""
    uow = _make_uow({("AAPL", "US"): SimpleNamespace(id="instr-aapl")})
    consumer = EarningsCalendarConsumer(uow_factory=lambda: uow, object_storage=None)
    envelope = _envelope(
        [
            {"code": "AAPL.US", "report_date": "2026-02-01"},
            {"code": "ZZZZ.US", "report_date": "2026-02-02"},  # unknown → skipped
        ]
    )

    rows = await consumer._build_rows(uow, envelope)

    assert len(rows) == 1
    assert rows[0]["instrument_id"] == "instr-aapl"


@pytest.mark.asyncio
async def test_build_rows_skips_missing_report_date_or_code() -> None:
    uow = _make_uow({("AAPL", "US"): SimpleNamespace(id="instr-aapl")})
    consumer = EarningsCalendarConsumer(uow_factory=lambda: uow, object_storage=None)
    envelope = _envelope(
        [
            {"code": "AAPL.US"},  # missing report_date → skipped
            {"report_date": "2026-02-01"},  # missing code → skipped
            "not-a-dict",  # malformed → skipped
        ]
    )

    rows = await consumer._build_rows(uow, envelope)

    assert rows == []


@pytest.mark.asyncio
async def test_build_rows_caches_resolution_per_distinct_code() -> None:
    """A repeated code is resolved only once (batch-resolve cache)."""
    uow = _make_uow({("AAPL", "US"): SimpleNamespace(id="instr-aapl")})
    consumer = EarningsCalendarConsumer(uow_factory=lambda: uow, object_storage=None)
    envelope = _envelope(
        [
            {"code": "AAPL.US", "report_date": "2026-02-01"},
            {"code": "AAPL.US", "report_date": "2026-05-01"},
        ]
    )

    rows = await consumer._build_rows(uow, envelope)

    assert len(rows) == 2
    # Two rows, same code → exactly ONE DB lookup.
    assert uow.instruments.find_by_symbol_exchange.await_count == 1


@pytest.mark.asyncio
async def test_build_rows_empty_earnings_list_is_ok() -> None:
    uow = _make_uow({})
    consumer = EarningsCalendarConsumer(uow_factory=lambda: uow, object_storage=None)
    assert await consumer._build_rows(uow, _envelope([])) == []


# ── process_message gates ───────────────────────────────────────────────────


def _make_consumer(uow: AsyncMock, storage: AsyncMock) -> EarningsCalendarConsumer:
    consumer = EarningsCalendarConsumer(uow_factory=lambda: uow, object_storage=storage)
    consumer._current_uow = uow
    return consumer


@pytest.mark.asyncio
async def test_process_message_ignores_other_dataset_types() -> None:
    """Non-earnings datasets on the shared topic are silently no-oped."""
    uow = AsyncMock()
    storage = AsyncMock()
    consumer = _make_consumer(uow, storage)

    await consumer.process_message(key=None, value={"dataset_type": "ohlcv"}, headers={})

    storage.get_bytes.assert_not_called()
    uow.ingestion_events.create_if_not_exists.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_duplicate_event_short_circuits() -> None:
    """A duplicate event (create_if_not_exists → False) never touches storage."""
    uow = AsyncMock()
    uow.ingestion_events.exists_by_content_hash = AsyncMock(return_value=False)
    uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=False)
    storage = AsyncMock()
    consumer = _make_consumer(uow, storage)

    await consumer.process_message(
        key=None,
        value={"dataset_type": "earnings_calendar", "event_id": "evt-1"},
        headers={},
    )

    storage.get_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_happy_path_upserts_rows() -> None:
    """End-to-end: new event → download → parse → insert_batch called."""
    uow = AsyncMock()
    uow.ingestion_events.exists_by_content_hash = AsyncMock(return_value=False)
    uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)
    uow.instruments.find_by_symbol_exchange = AsyncMock(return_value=SimpleNamespace(id="instr-aapl"))
    uow.earnings_calendar.insert_batch = AsyncMock(return_value=1)

    envelope_line = json.dumps(
        {
            "source": "eodhd",
            "payload": {"type": "Earnings", "earnings": [{"code": "AAPL.US", "report_date": "2026-02-01"}]},
        }
    )
    storage = AsyncMock()
    storage.get_bytes = AsyncMock(return_value=(envelope_line + "\n").encode())
    consumer = _make_consumer(uow, storage)

    await consumer.process_message(
        key=None,
        value={
            "dataset_type": "earnings_calendar",
            "event_id": "evt-2",
            "canonical_ref_bucket": "market-canonical",
            "canonical_ref_key": "earnings/2026.ndjson",
        },
        headers={},
    )

    uow.earnings_calendar.insert_batch.assert_awaited_once()
    (rows_arg,), _ = uow.earnings_calendar.insert_batch.await_args
    assert len(rows_arg) == 1
    assert rows_arg[0]["instrument_id"] == "instr-aapl"
    assert rows_arg[0]["report_date"] == date(2026, 2, 1)


# ── repository insert_batch SQL shape ───────────────────────────────────────


@pytest.mark.asyncio
async def test_repo_insert_batch_sql_shape_and_defaults() -> None:
    """insert_batch issues an ON CONFLICT ... COALESCE upsert and fills id."""
    session = AsyncMock()
    repo = PgEarningsCalendarRepository(session)

    offered = await repo.insert_batch([{"instrument_id": "instr-aapl", "report_date": date(2026, 2, 1)}])

    assert offered == 1
    session.execute.assert_awaited_once()
    sql_arg, params = session.execute.await_args.args
    sql_text = str(sql_arg)
    assert "INSERT INTO earnings_calendar" in sql_text
    assert "ON CONFLICT ON CONSTRAINT uq_earnings_calendar" in sql_text
    assert "COALESCE(EXCLUDED.eps_estimate" in sql_text
    assert "ingested_at  = now()" in sql_text
    # Optional columns defaulted to None; id filled with a UUIDv7.
    assert params["id"]
    assert params["fiscal_date"] is None
    assert params["eps_actual"] is None


@pytest.mark.asyncio
async def test_repo_insert_batch_empty_is_noop() -> None:
    session = AsyncMock()
    repo = PgEarningsCalendarRepository(session)
    assert await repo.insert_batch([]) == 0
    session.execute.assert_not_called()
