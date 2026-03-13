"""E2E scenario: full portfolio transaction flow.

Hits the LIVE portfolio service running on localhost:8001.
Started by: make test-e2e (docker-compose.test.yml --profile portfolio-test)

Workflow exercised:
  POST /tenants → POST /users → POST /portfolios
  → POST /transactions (BUY) → GET /holdings
  → POST /transactions (SELL) → GET /holdings
  → GET /transactions
  → Outbox event created in DB (white-box assertion)
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

_EXECUTED_AT = "2025-06-01T10:00:00Z"


async def test_full_transaction_flow(e2e_client: AsyncClient, e2e_db_session: AsyncSession) -> None:
    """Happy-path: create tenant/user/portfolio, BUY, SELL, verify holdings and transactions."""
    # 1. Create tenant
    resp = await e2e_client.post("/api/v1/tenants", json={"name": f"FlowCo-{uuid.uuid4().hex[:6]}"})
    assert resp.status_code == 201, resp.text
    tenant_id = resp.json()["id"]

    # 2. Create user
    resp = await e2e_client.post(
        "/api/v1/users",
        json={"tenant_id": tenant_id, "email": f"trader-{uuid.uuid4().hex[:6]}@flowco.com"},
    )
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]

    # 3. Create portfolio
    resp = await e2e_client.post(
        "/api/v1/portfolios",
        json={"name": f"E2E Portfolio {uuid.uuid4().hex[:6]}", "owner_user_id": user_id, "currency": "USD"},
        headers={"X-Tenant-ID": tenant_id},
    )
    assert resp.status_code == 201, resp.text
    portfolio_id = resp.json()["id"]

    # Verify PortfolioCreated event in outbox (white-box)
    from portfolio.infrastructure.db.models.outbox import OutboxEventModel
    from sqlalchemy import select

    result = await e2e_db_session.execute(
        select(OutboxEventModel).where(OutboxEventModel.event_type == "portfolio.created")
    )
    assert result.scalars().first() is not None, "PortfolioCreated event missing from outbox"

    # 4. Seed instrument directly via DB (no instrument-sync Kafka in test compose)
    instrument_id = await _seed_instrument(e2e_db_session, f"AAPL_{uuid.uuid4().hex[:4]}", "NASDAQ")

    common_headers = {"X-Tenant-ID": tenant_id, "X-Owner-ID": user_id}

    # 5. BUY 10 shares @ $150
    resp = await e2e_client.post(
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
    assert resp.status_code == 201, resp.text

    # 6. GET holdings → quantity=10, avg_cost=150
    resp = await e2e_client.get(f"/api/v1/holdings/{portfolio_id}", headers=common_headers)
    assert resp.status_code == 200, resp.text
    holdings = resp.json()
    assert len(holdings) == 1
    assert holdings[0]["quantity"] == "10.00000000"
    assert holdings[0]["average_cost"] == "150.00000000"

    # 7. SELL 5 shares @ $160
    resp = await e2e_client.post(
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
    assert resp.status_code == 201, resp.text

    # 8. GET holdings → quantity=5
    resp = await e2e_client.get(f"/api/v1/holdings/{portfolio_id}", headers=common_headers)
    assert resp.status_code == 200, resp.text
    holdings = resp.json()
    assert len(holdings) == 1
    assert holdings[0]["quantity"] == "5.00000000"

    # 9. GET transactions → 2 records
    resp = await e2e_client.get(
        "/api/v1/transactions",
        headers={**common_headers, "X-Portfolio-ID": portfolio_id},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2

    # 10. Dispatcher drains outbox rows for this tenant
    delivered = 0
    for _ in range(30):
        result = await e2e_db_session.execute(
            select(OutboxEventModel).where(
                OutboxEventModel.tenant_id == tenant_id,
                OutboxEventModel.status == "delivered",
            )
        )
        delivered = len(result.scalars().all())
        await e2e_db_session.rollback()
        if delivered >= 3:
            break
        await asyncio.sleep(1.0)

    assert delivered >= 3, "Expected dispatcher to deliver outbox events for the transaction flow"


async def test_readyz_returns_ok(e2e_client: AsyncClient) -> None:
    """GET /readyz returns 200 when DB is reachable."""
    resp = await e2e_client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_healthz_returns_ok(e2e_client: AsyncClient) -> None:
    """GET /healthz always returns 200."""
    resp = await e2e_client.get("/healthz")
    assert resp.status_code == 200


async def test_create_tenant_returns_valid_id(e2e_client: AsyncClient) -> None:
    """POST /tenants returns 201 with a UUID id field."""
    resp = await e2e_client.post("/api/v1/tenants", json={"name": f"IdCheck-{uuid.uuid4().hex[:6]}"})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "id" in data
    uuid.UUID(data["id"])  # raises if not a valid UUID


async def test_duplicate_portfolio_name_rejected(e2e_client: AsyncClient) -> None:
    """POST /portfolios with duplicate name for same owner returns 409 or 422."""
    resp = await e2e_client.post("/api/v1/tenants", json={"name": f"DupCo-{uuid.uuid4().hex[:6]}"})
    tenant_id = resp.json()["id"]
    resp = await e2e_client.post(
        "/api/v1/users",
        json={"tenant_id": tenant_id, "email": f"dup-{uuid.uuid4().hex[:6]}@dupco.com"},
    )
    user_id = resp.json()["id"]

    name = f"DupPortfolio-{uuid.uuid4().hex[:6]}"
    headers = {"X-Tenant-ID": tenant_id}

    resp = await e2e_client.post(
        "/api/v1/portfolios",
        json={"name": name, "owner_user_id": user_id, "currency": "USD"},
        headers=headers,
    )
    assert resp.status_code == 201

    resp = await e2e_client.post(
        "/api/v1/portfolios",
        json={"name": name, "owner_user_id": user_id, "currency": "USD"},
        headers=headers,
    )
    assert resp.status_code in (409, 422), f"Expected conflict, got {resp.status_code}: {resp.text}"


async def test_sell_exceeding_holdings_rejected(e2e_client: AsyncClient, e2e_db_session: AsyncSession) -> None:
    """SELL more than held quantity returns 409 or 422 (InsufficientHoldingsError)."""
    resp = await e2e_client.post("/api/v1/tenants", json={"name": f"SellCo-{uuid.uuid4().hex[:6]}"})
    tenant_id = resp.json()["id"]
    resp = await e2e_client.post(
        "/api/v1/users",
        json={"tenant_id": tenant_id, "email": f"sell-{uuid.uuid4().hex[:6]}@sellco.com"},
    )
    user_id = resp.json()["id"]
    resp = await e2e_client.post(
        "/api/v1/portfolios",
        json={"name": f"SellPort-{uuid.uuid4().hex[:6]}", "owner_user_id": user_id, "currency": "USD"},
        headers={"X-Tenant-ID": tenant_id},
    )
    portfolio_id = resp.json()["id"]
    instrument_id = await _seed_instrument(e2e_db_session, f"SELL_{uuid.uuid4().hex[:4]}", "NYSE")
    headers = {"X-Tenant-ID": tenant_id, "X-Owner-ID": user_id}

    await e2e_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio_id,
            "instrument_id": str(instrument_id),
            "transaction_type": "BUY",
            "direction": "INFLOW",
            "quantity": "2",
            "price": "100.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
        headers=headers,
    )

    resp = await e2e_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio_id,
            "instrument_id": str(instrument_id),
            "transaction_type": "SELL",
            "direction": "OUTFLOW",
            "quantity": "5",
            "price": "110.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
        headers=headers,
    )
    assert resp.status_code in (409, 422), f"Expected rejection, got {resp.status_code}: {resp.text}"


async def test_archive_portfolio(e2e_client: AsyncClient) -> None:
    """DELETE /portfolios/{id} transitions portfolio to ARCHIVED status."""
    resp = await e2e_client.post("/api/v1/tenants", json={"name": f"ArchCo-{uuid.uuid4().hex[:6]}"})
    tenant_id = resp.json()["id"]
    resp = await e2e_client.post(
        "/api/v1/users",
        json={"tenant_id": tenant_id, "email": f"arch-{uuid.uuid4().hex[:6]}@archco.com"},
    )
    user_id = resp.json()["id"]
    resp = await e2e_client.post(
        "/api/v1/portfolios",
        json={"name": f"ToArchive-{uuid.uuid4().hex[:6]}", "owner_user_id": user_id, "currency": "USD"},
        headers={"X-Tenant-ID": tenant_id},
    )
    assert resp.status_code == 201
    portfolio_id = resp.json()["id"]

    resp = await e2e_client.delete(
        f"/api/v1/portfolios/{portfolio_id}",
        headers={"X-Tenant-ID": tenant_id, "X-Owner-ID": user_id},
    )
    assert resp.status_code in (200, 204), f"Expected archive success, got {resp.status_code}: {resp.text}"


# ── helpers ───────────────────────────────────────────────────────────────────


async def _seed_instrument(session: AsyncSession, symbol: str, exchange: str) -> uuid.UUID:
    """Insert a minimal InstrumentRef row directly into the DB for transaction tests."""
    from portfolio.infrastructure.db.models.instrument import InstrumentModel

    inst_id = uuid.uuid4()
    session.add(
        InstrumentModel(
            id=inst_id,
            symbol=symbol,
            exchange=exchange,
            name=f"{symbol} Corp",
            currency="USD",
            asset_class="equity",
            source_event_id=uuid.uuid4(),
        )
    )
    await session.commit()
    return inst_id
