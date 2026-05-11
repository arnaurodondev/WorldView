"""Integration tests for holdings API endpoint.

After PLAN-0025, routes read tenant_id / user_id from JWT state.
X-Tenant-ID and X-Owner-ID headers are ignored.

The integration_client fixture pre-seeds INTEGRATION_TENANT_ID / USER_ID so
that portfolio creation (which validates tenant + user existence) succeeds.
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.helpers import (
    INTEGRATION_TENANT2_ID,
    INTEGRATION_USER3_ID,
    INTEGRATION_USER_ID,
    make_jwt_headers,
    seed_tenant,
    seed_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_EXECUTED_AT = "2025-01-01T12:00:00Z"


async def test_holdings_empty_before_transaction(integration_client, db_session) -> None:
    """GET /api/v1/holdings/{portfolio_id} returns empty paginated envelope before any transaction.

    PLAN-0088 (2026-05-10): assertion updated from raw list `[]` to paginated
    envelope. The endpoint switched to a paginated response shape
    (``{items, limit, offset, total}``) when read paths were rewired through
    ReadOnlyUnitOfWork (PLAN-0076 B-5). The old fixture failure masked this
    drift; with the fixture fixed, the assertion now matches current behavior.
    """
    portfolio_id = await _create_portfolio(integration_client)

    resp = await integration_client.get(f"/api/v1/holdings/{portfolio_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_holdings_unchanged_after_buy_without_snapshot(
    integration_client,
    db_session,
) -> None:
    """A BUY transaction alone does NOT mutate holdings — broker snapshot is sole writer.

    PLAN-0088 (2026-05-10): test renamed and assertions inverted to reflect
    BP-264 / PLAN-0046 T-46-1-03. record_transaction.py is now history-only;
    Holdings are derived exclusively from broker position snapshots via
    UpsertHoldingsFromSnapshotUseCase. Manual transactions are recorded in
    history but no longer auto-update holdings (that path silently doubled
    quantities when SnapTrade emitted the same activity twice via legacy +
    per-account fallback paths). See record_transaction.py:168-181.

    The original assertion (BUY → 1 holding row) was masked by the
    read_factory fixture bug for several months.
    """
    portfolio_id = await _create_portfolio(integration_client)
    instrument_id = await _seed_instrument(db_session, "AAPL", "NYSE")

    # BUY 10 @ 150 — recorded in transactions table + outbox event, but no
    # holding row is created (snapshot upsert is the sole writer).
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
    )
    assert resp.status_code == 201

    resp = await integration_client.get(f"/api/v1/holdings/{portfolio_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_holdings_cross_tenant_denied(integration_client, db_session) -> None:
    """GET holdings with a different tenant_id returns 403 or 404."""
    # Seed tenant2 and a user under it.
    await seed_tenant(db_session, INTEGRATION_TENANT2_ID, "Tenant Two")
    await seed_user(db_session, INTEGRATION_USER3_ID, INTEGRATION_TENANT2_ID, "user3-hold@t2.com")

    # Create portfolio under tenant1 (INTEGRATION_TENANT_ID via default JWT).
    portfolio_id = await _create_portfolio(integration_client)

    # Tenant2 user attempts to read tenant1's holdings — must be denied.
    tenant2_headers = make_jwt_headers(INTEGRATION_TENANT2_ID, INTEGRATION_USER3_ID)
    resp = await integration_client.get(
        f"/api/v1/holdings/{portfolio_id}",
        headers=tenant2_headers,
    )
    assert resp.status_code in (403, 404), f"Expected 403/404, got {resp.status_code}"


# ── helpers ───────────────────────────────────────────────────────────────────


async def _create_portfolio(client) -> str:  # type: ignore[no-untyped-def]
    """Create a portfolio for INTEGRATION_USER_ID and return its id."""
    resp = await client.post(
        "/api/v1/portfolios",
        json={
            "name": f"Holdings Test Portfolio {uuid.uuid4().hex[:8]}",
            "owner_user_id": INTEGRATION_USER_ID,
            "currency": "USD",
        },
    )
    assert resp.status_code == 201, f"create_portfolio failed: {resp.text}"
    return resp.json()["id"]


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
