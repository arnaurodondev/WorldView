"""Integration tests for transaction API endpoints.

After PLAN-0025, routes read tenant_id / user_id from JWT state.
X-Tenant-ID and X-Owner-ID headers are completely ignored.

The integration_client fixture pre-seeds INTEGRATION_TENANT_ID / USER_ID so
that portfolio creation (which validates tenant + user existence) succeeds.
"""

from __future__ import annotations

import uuid

import pytest
from tests.integration.helpers import (
    INTEGRATION_USER_ID,
    OutboxAssertions,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_EXECUTED_AT = "2025-01-01T12:00:00Z"


async def test_buy_transaction_creates_records(integration_client, db_session) -> None:
    """POST /api/v1/transactions (BUY) creates transaction record + transaction.recorded outbox event.

    PLAN-0088 (2026-05-10): assertion for ``holding.changed`` removed because
    BP-264 / PLAN-0046 T-46-1-03 made record_transaction.py history-only —
    holdings are derived from the broker snapshot
    (UpsertHoldingsFromSnapshotUseCase) which is now the sole owner of
    HoldingChanged. See record_transaction.py:179-181 for rationale. The old
    fixture failure masked this drift; now the assertion matches behaviour.
    """
    portfolio_id = await _create_portfolio(integration_client)
    instrument_id = await _seed_instrument(db_session, "AAPL", "NASDAQ")

    resp = await integration_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio_id,
            "instrument_id": str(instrument_id),
            "transaction_type": "BUY",
            "direction": "INFLOW",
            "quantity": "10",
            "price": "150.00",
            "fees": "0.50",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["quantity"] == "10.00000000"

    await OutboxAssertions.assert_event_type_in_outbox(db_session, "transaction.recorded")


async def test_idempotency_replay_no_duplicate(integration_client, db_session) -> None:
    """Two requests with the same Idempotency-Key produce only one transaction + outbox event."""
    portfolio_id = await _create_portfolio(integration_client)
    instrument_id = await _seed_instrument(db_session, "MSFT", "NASDAQ")
    idem_key = str(uuid.uuid4())

    body = {
        "portfolio_id": portfolio_id,
        "instrument_id": str(instrument_id),
        "transaction_type": "BUY",
        "direction": "INFLOW",
        "quantity": "5",
        "price": "200.00",
        "currency": "USD",
        "executed_at": _EXECUTED_AT,
    }
    headers = {"Idempotency-Key": idem_key}

    # Snapshot count before requests
    count_before = await OutboxAssertions.count_events_by_type(db_session, "transaction.recorded")

    resp1 = await integration_client.post("/api/v1/transactions", json=body, headers=headers)
    assert resp1.status_code == 201

    resp2 = await integration_client.post("/api/v1/transactions", json=body, headers=headers)
    assert resp2.status_code == 201
    assert resp1.json()["id"] == resp2.json()["id"]

    # Only 1 new transaction.recorded event added (idempotent replay — not 2)
    count_after = await OutboxAssertions.count_events_by_type(db_session, "transaction.recorded")
    assert count_after - count_before == 1


async def test_list_transactions(integration_client, db_session) -> None:
    """GET /api/v1/transactions returns all transactions for a portfolio."""
    portfolio_id = await _create_portfolio(integration_client)
    instrument_id = await _seed_instrument(db_session, "GOOGL", "NASDAQ")

    body = {
        "portfolio_id": portfolio_id,
        "instrument_id": str(instrument_id),
        "transaction_type": "BUY",
        "direction": "INFLOW",
        "quantity": "3",
        "price": "100.00",
        "currency": "USD",
        "executed_at": _EXECUTED_AT,
    }

    await integration_client.post("/api/v1/transactions", json=body)

    # GET /api/v1/transactions reads portfolio_id from X-Portfolio-ID header (not query params).
    resp = await integration_client.get(
        "/api/v1/transactions",
        headers={"X-Portfolio-ID": portfolio_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Portfolio is freshly created — exactly 1 transaction expected.
    assert data["total"] == 1
    assert data["items"][0]["portfolio_id"] == portfolio_id


async def test_transaction_requires_positive_quantity(integration_client, db_session) -> None:
    """POST /api/v1/transactions with quantity=0 returns 422."""
    portfolio_id = await _create_portfolio(integration_client)
    instrument_id = await _seed_instrument(db_session, "AMZN", "NASDAQ")

    resp = await integration_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio_id,
            "instrument_id": str(instrument_id),
            "transaction_type": "BUY",
            "direction": "INFLOW",
            "quantity": "0",
            "price": "100.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
    )
    assert resp.status_code == 422


async def test_transaction_requires_positive_price(integration_client, db_session) -> None:
    """POST /api/v1/transactions with price=0 returns 422."""
    portfolio_id = await _create_portfolio(integration_client)
    instrument_id = await _seed_instrument(db_session, "META", "NASDAQ")

    resp = await integration_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio_id,
            "instrument_id": str(instrument_id),
            "transaction_type": "BUY",
            "direction": "INFLOW",
            "quantity": "5",
            "price": "0",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
    )
    assert resp.status_code == 422


# ── helpers ───────────────────────────────────────────────────────────────────


async def _create_portfolio(client) -> str:  # type: ignore[no-untyped-def]
    """Create a portfolio for INTEGRATION_USER_ID and return its id."""
    resp = await client.post(
        "/api/v1/portfolios",
        json={
            "name": f"Tx Test Portfolio {uuid.uuid4().hex[:8]}",
            "owner_user_id": INTEGRATION_USER_ID,
            "currency": "USD",
        },
    )
    assert resp.status_code == 201, f"create_portfolio failed: {resp.text}"
    return resp.json()["id"]


async def _seed_instrument(db_session, symbol: str, exchange: str) -> uuid.UUID:
    """Upsert an instrument into the test DB and return its ID.

    Uses ON CONFLICT DO NOTHING so repeated calls across the session-scoped
    testcontainer don't raise UniqueViolationError.
    """
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
            name=f"{symbol} Inc.",
            currency="USD",
            asset_class="equity",
            source_event_id=uuid.uuid4(),
        )
        .on_conflict_do_nothing(constraint="uq_instruments_symbol_exchange")
    )
    await db_session.execute(stmt)
    await db_session.commit()

    # If the row already existed, fetch its actual ID
    result = await db_session.execute(
        select(InstrumentModel.id).where(
            InstrumentModel.symbol == symbol,
            InstrumentModel.exchange == exchange,
        ),
    )
    return result.scalar_one()
