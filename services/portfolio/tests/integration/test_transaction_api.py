"""Integration tests for transaction API endpoints."""

from __future__ import annotations

import uuid

import pytest

from tests.integration.helpers import OutboxAssertions, make_portfolio, make_tenant, make_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_EXECUTED_AT = "2025-01-01T12:00:00Z"


async def test_buy_transaction_creates_records(integration_client, db_session) -> None:
    """POST /api/v1/transactions (BUY) creates transaction + holding + outbox events."""
    tenant = await make_tenant(integration_client, name="TxCo")
    user = await make_user(integration_client, tenant["id"])
    portfolio = await make_portfolio(integration_client, tenant["id"], user["id"])
    instrument_id = await _seed_instrument(db_session, "AAPL", "NASDAQ")

    resp = await integration_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio["id"],
            "instrument_id": str(instrument_id),
            "transaction_type": "BUY",
            "direction": "INFLOW",
            "quantity": "10",
            "price": "150.00",
            "fees": "0.50",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
        headers={
            "X-Tenant-ID": tenant["id"],
            "X-Owner-ID": user["id"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["quantity"] == "10.00000000"

    await OutboxAssertions.assert_event_type_in_outbox(db_session, "transaction.recorded")
    await OutboxAssertions.assert_event_type_in_outbox(db_session, "holding.changed")


async def test_idempotency_replay_no_duplicate(integration_client, db_session) -> None:
    """Two requests with the same Idempotency-Key produce only one transaction + outbox event."""
    tenant = await make_tenant(integration_client, name="IdemCo")
    user = await make_user(integration_client, tenant["id"])
    portfolio = await make_portfolio(integration_client, tenant["id"], user["id"])
    instrument_id = await _seed_instrument(db_session, "MSFT", "NASDAQ")
    idem_key = str(uuid.uuid4())

    body = {
        "portfolio_id": portfolio["id"],
        "instrument_id": str(instrument_id),
        "transaction_type": "BUY",
        "direction": "INFLOW",
        "quantity": "5",
        "price": "200.00",
        "currency": "USD",
        "executed_at": _EXECUTED_AT,
    }
    headers = {
        "X-Tenant-ID": tenant["id"],
        "X-Owner-ID": user["id"],
        "Idempotency-Key": idem_key,
    }

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
    tenant = await make_tenant(integration_client, name="ListTxCo")
    user = await make_user(integration_client, tenant["id"])
    portfolio = await make_portfolio(integration_client, tenant["id"], user["id"])
    instrument_id = await _seed_instrument(db_session, "GOOGL", "NASDAQ")

    body = {
        "portfolio_id": portfolio["id"],
        "instrument_id": str(instrument_id),
        "transaction_type": "BUY",
        "direction": "INFLOW",
        "quantity": "3",
        "price": "100.00",
        "currency": "USD",
        "executed_at": _EXECUTED_AT,
    }
    headers = {"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]}

    await integration_client.post("/api/v1/transactions", json=body, headers=headers)

    resp = await integration_client.get(
        "/api/v1/transactions",
        headers={
            "X-Tenant-ID": tenant["id"],
            "X-Owner-ID": user["id"],
            "X-Portfolio-ID": portfolio["id"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["portfolio_id"] == portfolio["id"]


# ── helpers ───────────────────────────────────────────────────────────────────


async def _seed_instrument(db_session, symbol: str, exchange: str) -> uuid.UUID:
    """Insert an instrument directly into the test DB and return its ID."""
    from portfolio.infrastructure.db.models.instrument import InstrumentModel

    inst_id = uuid.uuid4()
    inst = InstrumentModel(
        id=inst_id,
        symbol=symbol,
        exchange=exchange,
        name=f"{symbol} Inc.",
        currency="USD",
        asset_class="equity",
        source_event_id=uuid.uuid4(),
    )
    db_session.add(inst)
    await db_session.commit()
    return inst_id
