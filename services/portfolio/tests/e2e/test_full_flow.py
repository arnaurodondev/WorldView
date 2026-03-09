"""E2E QA scenario: full transaction flow.

Tests the full happy path:
1. Create tenant → user → portfolio
2. BUY 10 AAPL @ 150 → verify holdings
3. SELL 5 AAPL @ 160 → verify holdings updated
4. List transactions → verify 2 transactions

Can run against integration DB (integration_client fixture) or full infra.
Marked e2e but runnable with integration_client fixture.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

_EXECUTED_AT = "2025-06-01T10:00:00Z"


async def test_full_transaction_flow(integration_client, db_session) -> None:
    """Full happy-path: create tenant/user/portfolio, BUY, SELL, verify holdings and transactions."""
    # 1. Create tenant
    resp = await integration_client.post("/api/v1/tenants", json={"name": "FlowCo"})
    assert resp.status_code == 201
    tenant_id = resp.json()["id"]

    # 2. Create user
    resp = await integration_client.post("/api/v1/users", json={"tenant_id": tenant_id, "email": "trader@flowco.com"})
    assert resp.status_code == 201
    user_id = resp.json()["id"]

    # 3. Create portfolio
    resp = await integration_client.post(
        "/api/v1/portfolios",
        json={"name": "AAPL Portfolio", "owner_user_id": user_id, "currency": "USD"},
        headers={"X-Tenant-ID": tenant_id},
    )
    assert resp.status_code == 201
    portfolio_id = resp.json()["id"]

    # Verify PortfolioCreated event in outbox
    from portfolio.infrastructure.db.models.outbox import OutboxEventModel
    from sqlalchemy import select

    result = await db_session.execute(
        select(OutboxEventModel).where(OutboxEventModel.event_type == "portfolio.created")
    )
    assert result.scalars().first() is not None, "PortfolioCreated event missing from outbox"

    # 4. Seed instrument
    instrument_id = await _seed_instrument(db_session, "AAPL", "NASDAQ")

    common_headers = {"X-Tenant-ID": tenant_id, "X-Owner-ID": user_id}

    # 5. BUY 10 shares @ $150
    resp = await integration_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio_id,
            "instrument_id": str(instrument_id),
            "transaction_type": "BUY",
            "direction": "INFLOW",
            "quantity": "10",
            "price": "150.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
        headers=common_headers,
    )
    assert resp.status_code == 201

    # 6. GET holdings → quantity=10, avg_cost=150
    resp = await integration_client.get(f"/api/v1/holdings/{portfolio_id}", headers=common_headers)
    assert resp.status_code == 200
    holdings = resp.json()
    assert len(holdings) == 1
    assert holdings[0]["quantity"] == "10.00000000"
    assert holdings[0]["average_cost"] == "150.00000000"

    # 7. SELL 5 shares @ $160
    resp = await integration_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio_id,
            "instrument_id": str(instrument_id),
            "transaction_type": "SELL",
            "direction": "OUTFLOW",
            "quantity": "5",
            "price": "160.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
        headers=common_headers,
    )
    assert resp.status_code == 201

    # 8. GET holdings → quantity=5
    resp = await integration_client.get(f"/api/v1/holdings/{portfolio_id}", headers=common_headers)
    assert resp.status_code == 200
    holdings = resp.json()
    assert len(holdings) == 1
    assert holdings[0]["quantity"] == "5.00000000"

    # 9. GET transactions → 2 transactions
    resp = await integration_client.get(
        "/api/v1/transactions",
        headers={**common_headers, "X-Portfolio-ID": portfolio_id},
    )
    assert resp.status_code == 200
    transactions = resp.json()
    assert len(transactions) == 2


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
