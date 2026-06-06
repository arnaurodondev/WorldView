"""E2E scenario: full portfolio transaction flow.

Hits the LIVE portfolio service running on localhost:8001.
Started by: make test-e2e (docker-compose.test.yml --profile portfolio-test)

Workflow exercised:
  DB-seed tenant/user → POST /portfolios
  → POST /transactions (BUY) → GET /holdings
  → POST /transactions (SELL) → GET /holdings
  → GET /transactions
  → Outbox event created in DB (white-box assertion)

Auth note (PRD-0025 Wave C): POST /tenants now requires role=system
(set by InternalJWTMiddleware from S9). E2E tests that need a tenant/user
seed directly via DB to avoid requiring S9 in the test compose.
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


def make_e2e_jwt(tenant_id: str, user_id: str, role: str = "system") -> str:
    """Issue a per-test JWT bound to a seeded (tenant_id, user_id).

    The route handlers read tenant_id / user_id from request.state populated
    by InternalJWTMiddleware (they ignore X-Tenant-ID / X-Owner-ID after
    PRD-0025). Each E2E test seeds its own tenant + user UUID, so it MUST
    pass a JWT whose claims contain those exact UUIDs — otherwise
    ``UUID(str(request.state.tenant_id))`` raises ValueError → 500
    INTERNAL_ERROR (the CI failure pattern fixed by this helper).
    """
    import time

    import jwt as _jwt

    payload = {
        "iss": "worldview-gateway",
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return _jwt.encode(payload, "e2e-test-secret", algorithm="HS256")


async def test_full_transaction_flow(e2e_client: AsyncClient, e2e_db_session: AsyncSession) -> None:
    """Happy-path: create tenant/user via DB seed, BUY, SELL, verify holdings and transactions."""
    # 1. Seed tenant + user directly (POST /tenants now requires role=system from S9 JWT)
    tenant_id, user_id = await _seed_tenant_and_user(e2e_db_session, email=f"trader-{uuid.uuid4().hex[:6]}@flowco.com")
    # The portfolio route extracts tenant_id/user_id from the JWT (not from
    # X-Tenant-ID / X-Owner-ID headers), so issue a JWT bound to the seeded
    # tenant + user — anything else fails ``UUID("e2e-tenant")`` → 500.
    auth_jwt = make_e2e_jwt(tenant_id=tenant_id, user_id=user_id)

    # 2. Create portfolio via API (no auth restriction on POST /portfolios)
    resp = await e2e_client.post(
        "/api/v1/portfolios",
        json={"name": f"E2E Portfolio {uuid.uuid4().hex[:6]}", "owner_user_id": user_id, "currency": "USD"},
        headers={"X-Tenant-ID": tenant_id, "X-Internal-JWT": auth_jwt},
    )
    assert resp.status_code == 201, resp.text
    portfolio_id = resp.json()["id"]

    # Verify PortfolioCreated event in outbox (white-box)
    from portfolio.infrastructure.db.models.outbox import OutboxEventModel
    from sqlalchemy import select

    result = await e2e_db_session.execute(
        select(OutboxEventModel).where(OutboxEventModel.event_type == "portfolio.created"),
    )
    assert result.scalars().first() is not None, "PortfolioCreated event missing from outbox"

    # 3. Seed instrument directly via DB (no instrument-sync Kafka in test compose)
    instrument_id = await _seed_instrument(e2e_db_session, f"AAPL_{uuid.uuid4().hex[:4]}", "NASDAQ")

    common_headers = {"X-Tenant-ID": tenant_id, "X-Owner-ID": user_id, "X-Internal-JWT": auth_jwt}

    # 4. BUY 10 shares @ $150
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

    # 5. GET holdings → quantity=10, avg_cost=150
    resp = await e2e_client.get(f"/api/v1/holdings/{portfolio_id}", headers=common_headers)
    assert resp.status_code == 200, resp.text
    holdings = resp.json()
    assert len(holdings) == 1
    assert holdings[0]["quantity"] == "10.00000000"
    assert holdings[0]["average_cost"] == "150.00000000"

    # 6. SELL 5 shares @ $160
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

    # 7. GET holdings → quantity=5
    resp = await e2e_client.get(f"/api/v1/holdings/{portfolio_id}", headers=common_headers)
    assert resp.status_code == 200, resp.text
    holdings = resp.json()
    assert len(holdings) == 1
    assert holdings[0]["quantity"] == "5.00000000"

    # 8. GET transactions → paginated payload with 2 records
    resp = await e2e_client.get(
        "/api/v1/transactions",
        headers={**common_headers, "X-Portfolio-ID": portfolio_id},
    )
    assert resp.status_code == 200, resp.text
    transactions = resp.json()
    assert transactions["total"] == 2
    assert len(transactions["items"]) == 2

    # 9. Outbox rows are persisted for this tenant (delivery is async/best-effort in test infra)
    outbox_rows = 0
    for _ in range(10):
        result = await e2e_db_session.execute(
            select(OutboxEventModel).where(
                OutboxEventModel.tenant_id == tenant_id,
            ),
        )
        outbox_rows = len(result.scalars().all())
        await e2e_db_session.rollback()
        if outbox_rows >= 3:
            break
        await asyncio.sleep(1.0)

    assert outbox_rows >= 3, "Expected outbox events to be recorded for the transaction flow"


async def test_readyz_returns_ok(e2e_client: AsyncClient) -> None:
    """GET /readyz returns 200 when DB is reachable."""
    resp = await e2e_client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_healthz_returns_ok(e2e_client: AsyncClient) -> None:
    """GET /healthz always returns 200."""
    resp = await e2e_client.get("/healthz")
    assert resp.status_code == 200


async def test_create_tenant_requires_system_role(unauthenticated_e2e_client: AsyncClient) -> None:
    """POST /tenants without X-Internal-JWT → 401 (SEC-005 fix enforced in E2E).

    The endpoint now requires role=system via InternalJWTMiddleware (PRD-0025 Wave C).
    Callers without a valid JWT from S9 gateway receive 401.
    """
    resp = await unauthenticated_e2e_client.post("/api/v1/tenants", json={"name": f"NoCreds-{uuid.uuid4().hex[:6]}"})
    # Without X-Internal-JWT header, the middleware returns 401
    assert resp.status_code == 401, f"Expected 401 (SEC-005), got {resp.status_code}: {resp.text}"


async def test_duplicate_portfolio_name_rejected(e2e_client: AsyncClient, e2e_db_session: AsyncSession) -> None:
    """POST /portfolios with duplicate name for same owner returns 409 or 422."""
    tenant_id, user_id = await _seed_tenant_and_user(e2e_db_session, email=f"dup-{uuid.uuid4().hex[:6]}@dupco.com")
    name = f"DupPortfolio-{uuid.uuid4().hex[:6]}"
    # JWT bound to seeded tenant — route reads tenant_id from JWT, not header.
    headers = {"X-Tenant-ID": tenant_id, "X-Internal-JWT": make_e2e_jwt(tenant_id, user_id)}

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
    tenant_id, user_id = await _seed_tenant_and_user(e2e_db_session, email=f"sell-{uuid.uuid4().hex[:6]}@sellco.com")
    auth_jwt = make_e2e_jwt(tenant_id=tenant_id, user_id=user_id)
    resp = await e2e_client.post(
        "/api/v1/portfolios",
        json={"name": f"SellPort-{uuid.uuid4().hex[:6]}", "owner_user_id": user_id, "currency": "USD"},
        headers={"X-Tenant-ID": tenant_id, "X-Internal-JWT": auth_jwt},
    )
    portfolio_id = resp.json()["id"]
    instrument_id = await _seed_instrument(e2e_db_session, f"SELL_{uuid.uuid4().hex[:4]}", "NYSE")
    headers = {"X-Tenant-ID": tenant_id, "X-Owner-ID": user_id, "X-Internal-JWT": auth_jwt}

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
            "quantity": "999",  # exceeds held quantity
            "price": "100.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
        headers=headers,
    )
    assert resp.status_code in (409, 422), f"Expected business rule rejection, got {resp.status_code}: {resp.text}"


async def test_archive_portfolio(e2e_client: AsyncClient, e2e_db_session: AsyncSession) -> None:
    """DELETE /portfolios/{id} transitions portfolio to ARCHIVED status."""
    tenant_id, user_id = await _seed_tenant_and_user(e2e_db_session, email=f"arch-{uuid.uuid4().hex[:6]}@archco.com")
    auth_jwt = make_e2e_jwt(tenant_id=tenant_id, user_id=user_id)
    resp = await e2e_client.post(
        "/api/v1/portfolios",
        json={"name": f"ToArchive-{uuid.uuid4().hex[:6]}", "owner_user_id": user_id, "currency": "USD"},
        headers={"X-Tenant-ID": tenant_id, "X-Internal-JWT": auth_jwt},
    )
    assert resp.status_code == 201
    portfolio_id = resp.json()["id"]

    resp = await e2e_client.delete(
        f"/api/v1/portfolios/{portfolio_id}",
        headers={"X-Tenant-ID": tenant_id, "X-Owner-ID": user_id, "X-Internal-JWT": auth_jwt},
    )
    assert resp.status_code in (200, 204), f"Expected archive success, got {resp.status_code}: {resp.text}"


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _seed_tenant_and_user(session: AsyncSession, email: str) -> tuple[str, str]:
    """Seed a tenant + user directly in the DB; return (tenant_id, user_id) as strings.

    Used instead of POST /tenants (which now requires role=system from S9 JWT).
    """
    from portfolio.infrastructure.db.models.tenant import TenantModel
    from portfolio.infrastructure.db.models.user import UserModel

    t_id = uuid.uuid4()
    u_id = uuid.uuid4()

    session.add(TenantModel(id=t_id, name=f"E2ETenant-{t_id.hex[:6]}", status="active"))
    session.add(
        UserModel(
            id=u_id,
            tenant_id=t_id,
            email=email,
            status="active",
        ),
    )
    await session.commit()
    return str(t_id), str(u_id)


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
        ),
    )
    await session.commit()
    return inst_id
