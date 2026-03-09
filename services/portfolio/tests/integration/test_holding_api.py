"""Integration tests for holdings API endpoint."""

from __future__ import annotations

import uuid

import pytest
from tests.integration.helpers import make_portfolio, make_tenant, make_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_EXECUTED_AT = "2025-01-01T12:00:00Z"


async def test_holdings_empty_before_transaction(integration_client, db_session) -> None:
    """GET /api/v1/holdings/{portfolio_id} returns empty list before any transaction."""
    tenant = await make_tenant(integration_client, name="HoldCo")
    user = await make_user(integration_client, tenant["id"])
    portfolio = await make_portfolio(integration_client, tenant["id"], user["id"])

    resp = await integration_client.get(
        f"/api/v1/holdings/{portfolio['id']}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_holdings_updated_after_buy(integration_client, db_session) -> None:
    """After BUY transaction, GET holdings shows updated quantity and avg_cost."""
    tenant = await make_tenant(integration_client, name="BuyHoldCo")
    user = await make_user(integration_client, tenant["id"])
    portfolio = await make_portfolio(integration_client, tenant["id"], user["id"])
    instrument_id = await _seed_instrument(db_session, "AAPL", "NYSE")

    # BUY 10 @ 150
    await integration_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio["id"],
            "instrument_id": str(instrument_id),
            "transaction_type": "BUY",
            "direction": "INFLOW",
            "quantity": "10",
            "price": "150.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )

    resp = await integration_client.get(
        f"/api/v1/holdings/{portfolio['id']}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 200
    holdings = resp.json()
    assert len(holdings) == 1
    assert holdings[0]["quantity"] == "10.00000000"
    assert holdings[0]["average_cost"] == "150.00000000"
    assert holdings[0]["instrument_id"] == str(instrument_id)


async def test_holdings_cross_tenant_denied(integration_client, db_session) -> None:
    """GET holdings with wrong tenant returns 403/404."""
    tenant1 = await make_tenant(integration_client, name="HTenant1")
    tenant2 = await make_tenant(integration_client, name="HTenant2")
    user = await make_user(integration_client, tenant1["id"])
    portfolio = await make_portfolio(integration_client, tenant1["id"], user["id"])

    resp = await integration_client.get(
        f"/api/v1/holdings/{portfolio['id']}",
        headers={"X-Tenant-ID": tenant2["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code in (403, 404), f"Expected 403/404, got {resp.status_code}"


# ── helpers ───────────────────────────────────────────────────────────────────


async def _seed_instrument(db_session, symbol: str, exchange: str) -> uuid.UUID:
    from portfolio.infrastructure.db.models.instrument import InstrumentModel

    inst_id = uuid.uuid4()
    inst = InstrumentModel(
        id=inst_id,
        symbol=symbol,
        exchange=exchange,
        name=f"{symbol} Corp",
        currency="USD",
        asset_class="equity",
        source_event_id=uuid.uuid4(),
    )
    db_session.add(inst)
    await db_session.commit()
    return inst_id
