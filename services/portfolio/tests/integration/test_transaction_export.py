"""Integration tests for the transaction CSV export endpoint.

PLAN-0114 / T-W2-08 (FR-3): these tests run against a real PostgreSQL database
spun up by the test infrastructure (testcontainers or a Docker service).

Marked with pytest.mark.integration so they are excluded from the fast unit
test run (``pytest -m unit``) and only executed during full CI or when the
developer explicitly runs ``pytest -m integration``.
"""

from __future__ import annotations

import csv
import io
import uuid

import pytest

from tests.integration.helpers import INTEGRATION_USER_ID

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_BUY_TX = {
    "transaction_type": "BUY",
    "direction": "INFLOW",
    "quantity": "10",
    "price": "100.00",
    "fees": "0.00",
    "currency": "USD",
}


async def _create_portfolio(client) -> str:  # type: ignore[no-untyped-def]
    """Create a portfolio and return its ID."""
    resp = await client.post(
        "/api/v1/portfolios",
        json={
            "name": f"Export Test {uuid.uuid4().hex[:8]}",
            "owner_user_id": INTEGRATION_USER_ID,
            "currency": "USD",
        },
    )
    assert resp.status_code == 201, f"create_portfolio failed: {resp.text}"
    return resp.json()["id"]


async def _seed_instrument(db_session, symbol: str, exchange: str) -> uuid.UUID:
    """Insert an instrument row and return its ID."""
    from portfolio.infrastructure.db.models.instrument import InstrumentModel
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert

    inst_id = uuid.uuid4()
    stmt = (
        insert(InstrumentModel)
        .values(
            id=inst_id,
            symbol=symbol,
            exchange=exchange,
            name=f"{symbol} Corp.",
            currency="USD",
            asset_class="equity",
            source_event_id=uuid.uuid4(),
        )
        .on_conflict_do_nothing(constraint="uq_instruments_symbol_exchange")
    )
    await db_session.execute(stmt)
    await db_session.commit()
    result = await db_session.execute(
        select(InstrumentModel.id).where(
            InstrumentModel.symbol == symbol,
            InstrumentModel.exchange == exchange,
        ),
    )
    return result.scalar_one()


async def _post_tx(client, portfolio_id: str, instrument_id: str, executed_at: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
    """POST a transaction to the portfolio."""
    body = {
        "portfolio_id": portfolio_id,
        "instrument_id": instrument_id,
        "executed_at": executed_at,
        **_BUY_TX,
        **kwargs,
    }
    resp = await client.post("/api/v1/transactions", json=body)
    assert resp.status_code == 201, f"create_transaction failed: {resp.text}"


def _parse_csv_response(content: bytes) -> list[dict[str, str]]:
    """Parse the CSV response body into a list of row dicts."""
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
    return list(reader)


# ── core export test ──────────────────────────────────────────────────────────


async def test_export_10_transactions_row_count_and_headers(integration_client, db_session) -> None:
    """Seed 10 transactions, export, assert row count = 10 and column names correct.

    This is the acceptance criterion from T-W2-08: «seed 10 transactions, export,
    assert row count = 10 and column names correct».
    """
    portfolio_id = await _create_portfolio(integration_client)
    instrument_id = str(await _seed_instrument(db_session, "TSLA", "NASDAQ"))

    # Seed 10 BUY transactions on consecutive dates.
    for i in range(1, 11):
        executed_at = f"2026-0{i // 10 + 3}-{i % 10 + 1:02d}T10:00:00Z"
        if i <= 9:
            executed_at = f"2026-01-{i:02d}T10:00:00Z"
        else:
            executed_at = "2026-01-10T10:00:00Z"
        await _post_tx(integration_client, portfolio_id, instrument_id, executed_at)

    # Call the export endpoint.
    resp = await integration_client.get(
        f"/api/v1/portfolios/{portfolio_id}/transactions/export",
    )
    assert resp.status_code == 200, f"export failed: {resp.text}"
    assert "text/csv" in resp.headers.get("content-type", "")

    rows = _parse_csv_response(resp.content)
    assert len(rows) == 10, f"expected 10 rows, got {len(rows)}"

    # Verify column names match the expected headers.
    expected_columns = {
        "date",
        "ticker",
        "type",
        "trade_side",
        "quantity",
        "price",
        "fees",
        "currency",
        "total_value",
        "cost_basis_per_unit",
        "realized_pnl",
        "description",
    }
    actual_columns = set(rows[0].keys())
    assert actual_columns == expected_columns, f"Column mismatch: {actual_columns ^ expected_columns}"


async def test_export_content_disposition_header(integration_client, db_session) -> None:
    """Export response includes Content-Disposition: attachment header."""
    portfolio_id = await _create_portfolio(integration_client)
    instrument_id = str(await _seed_instrument(db_session, "NVDA", "NASDAQ"))
    await _post_tx(integration_client, portfolio_id, instrument_id, "2026-06-01T10:00:00Z")

    resp = await integration_client.get(
        f"/api/v1/portfolios/{portfolio_id}/transactions/export",
        params={"from_date": "2026-06-01", "to_date": "2026-06-30"},
    )
    assert resp.status_code == 200
    content_disp = resp.headers.get("content-disposition", "")
    assert "attachment" in content_disp
    assert "transactions_" in content_disp


async def test_export_empty_portfolio_returns_headers_only(integration_client, db_session) -> None:
    """Empty portfolio → valid CSV with headers and zero data rows."""
    portfolio_id = await _create_portfolio(integration_client)

    resp = await integration_client.get(
        f"/api/v1/portfolios/{portfolio_id}/transactions/export",
    )
    assert resp.status_code == 200
    rows = _parse_csv_response(resp.content)
    assert rows == []


async def test_export_date_filter_respected(integration_client, db_session) -> None:
    """from_date/to_date filter is applied server-side — rows outside range excluded."""
    portfolio_id = await _create_portfolio(integration_client)
    instrument_id = str(await _seed_instrument(db_session, "AMZN", "NASDAQ"))

    # Two transactions: one in January, one in March.
    await _post_tx(integration_client, portfolio_id, instrument_id, "2026-01-15T10:00:00Z")
    await _post_tx(integration_client, portfolio_id, instrument_id, "2026-03-15T10:00:00Z")

    # Export only January.
    resp = await integration_client.get(
        f"/api/v1/portfolios/{portfolio_id}/transactions/export",
        params={"from_date": "2026-01-01", "to_date": "2026-01-31"},
    )
    assert resp.status_code == 200
    rows = _parse_csv_response(resp.content)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-01-15"


async def test_export_invalid_date_range_returns_400(integration_client) -> None:
    """to_date < from_date → 400 Bad Request."""
    portfolio_id = await _create_portfolio(integration_client)

    resp = await integration_client.get(
        f"/api/v1/portfolios/{portfolio_id}/transactions/export",
        params={"from_date": "2026-06-30", "to_date": "2026-01-01"},
    )
    assert resp.status_code == 400


async def test_export_ticker_filter_case_insensitive(integration_client, db_session) -> None:
    """FQ-005: ticker filter is tested at integration level (SQL ILIKE path).

    Seeds two instruments (AAPL and TSLA) and two transactions.
    Exports with ticker='aapl' (lowercase) — only AAPL transaction is returned.
    Also verifies uppercase 'AAPL' returns the same result (case-insensitive).

    WHY integration test (not unit): FakeTransactionRepository does not implement
    ticker filtering (requires an instrument JOIN). This test exercises the ILIKE
    path in SqlAlchemyTransactionRepository._build_filter_clauses() against a
    real PostgreSQL database. See FQ-005 and fakes.py:_apply_tx_filter() comment.
    """
    portfolio_id = await _create_portfolio(integration_client)
    aapl_id = str(await _seed_instrument(db_session, "AAPL", "NASDAQ"))
    tsla_id = str(await _seed_instrument(db_session, "TSLA", "NASDAQ"))

    # Seed one AAPL transaction and one TSLA transaction.
    await _post_tx(integration_client, portfolio_id, aapl_id, "2026-03-01T10:00:00Z")
    await _post_tx(integration_client, portfolio_id, tsla_id, "2026-03-02T10:00:00Z")

    # --- lowercase ticker filter ---
    resp_lower = await integration_client.get(
        f"/api/v1/portfolios/{portfolio_id}/transactions/export",
        params={"ticker": "aapl"},
    )
    assert resp_lower.status_code == 200, f"lowercase ticker filter failed: {resp_lower.text}"
    rows_lower = _parse_csv_response(resp_lower.content)
    assert len(rows_lower) == 1, f"Expected 1 AAPL row, got {len(rows_lower)}"
    assert rows_lower[0]["ticker"] == "AAPL"

    # --- uppercase ticker filter ---
    resp_upper = await integration_client.get(
        f"/api/v1/portfolios/{portfolio_id}/transactions/export",
        params={"ticker": "AAPL"},
    )
    assert resp_upper.status_code == 200, f"uppercase ticker filter failed: {resp_upper.text}"
    rows_upper = _parse_csv_response(resp_upper.content)
    assert len(rows_upper) == 1, f"Expected 1 AAPL row (uppercase), got {len(rows_upper)}"
    assert rows_upper[0]["ticker"] == "AAPL"

    # --- TSLA filter should return the other transaction ---
    resp_tsla = await integration_client.get(
        f"/api/v1/portfolios/{portfolio_id}/transactions/export",
        params={"ticker": "tsla"},
    )
    assert resp_tsla.status_code == 200
    rows_tsla = _parse_csv_response(resp_tsla.content)
    assert len(rows_tsla) == 1
    assert rows_tsla[0]["ticker"] == "TSLA"
