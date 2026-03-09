"""Integration test helpers: factory functions and outbox assertions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from portfolio.infrastructure.db.models.outbox import OutboxEventModel
from sqlalchemy import select

if TYPE_CHECKING:
    from uuid import UUID

    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


class OutboxAssertions:
    """Helpers for asserting events in the outbox table."""

    @staticmethod
    async def assert_event_type_in_outbox(session: AsyncSession, event_type: str) -> OutboxEventModel:
        """Assert that at least one outbox event of *event_type* exists; return the first match."""
        result = await session.execute(select(OutboxEventModel).where(OutboxEventModel.event_type == event_type))
        row = result.scalars().first()
        assert row is not None, f"Expected outbox event of type {event_type!r} — none found"
        return row

    @staticmethod
    async def count_events_by_type(session: AsyncSession, event_type: str) -> int:
        result = await session.execute(select(OutboxEventModel).where(OutboxEventModel.event_type == event_type))
        return len(list(result.scalars().all()))


# ── API factory helpers ───────────────────────────────────────────────────────


async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
    """POST /api/v1/tenants and return the response JSON."""
    resp = await client.post("/api/v1/tenants", json={"name": name})
    assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
    return resp.json()


async def make_user(
    client: AsyncClient,
    tenant_id: UUID | str,
    email: str = "user@example.com",
) -> dict[str, Any]:
    """POST /api/v1/users and return the response JSON."""
    resp = await client.post(
        "/api/v1/users",
        json={"tenant_id": str(tenant_id), "email": email},
    )
    assert resp.status_code == 201, f"create_user failed: {resp.text}"
    return resp.json()


async def make_portfolio(
    client: AsyncClient,
    tenant_id: UUID | str,
    user_id: UUID | str,
    name: str = "Test Portfolio",
    currency: str = "USD",
) -> dict[str, Any]:
    """POST /api/v1/portfolios and return the response JSON."""
    resp = await client.post(
        "/api/v1/portfolios",
        json={"name": name, "owner_user_id": str(user_id), "currency": currency},
        headers={"X-Tenant-ID": str(tenant_id)},
    )
    assert resp.status_code == 201, f"create_portfolio failed: {resp.text}"
    return resp.json()


async def make_instrument(session: AsyncSession, symbol: str = "AAPL", exchange: str = "NASDAQ") -> UUID:
    """Insert an instrument directly into the DB and return its ID."""
    from uuid import uuid4

    from portfolio.infrastructure.db.models.instrument import InstrumentModel

    inst_id = uuid4()
    inst = InstrumentModel(
        id=inst_id,
        symbol=symbol,
        exchange=exchange,
        name=f"{symbol} Inc.",
        currency="USD",
        asset_class="equity",
        source_event_id=uuid4(),
    )
    session.add(inst)
    await session.flush()
    return inst_id


# ── Cross-tenant security helpers ─────────────────────────────────────────────


async def assert_cross_tenant_denied(
    client: AsyncClient,
    url: str,
    other_tenant_id: UUID | str,
    owner_id: UUID | str,
) -> None:
    """Assert that accessing *url* with a different tenant_id returns 403 or 404."""
    resp = await client.get(
        url,
        headers={
            "X-Tenant-ID": str(other_tenant_id),
            "X-Owner-ID": str(owner_id),
        },
    )
    assert resp.status_code in (
        403,
        404,
    ), f"Expected 403/404 for cross-tenant access, got {resp.status_code}: {resp.text}"
