"""Integration tests for the watchlist Valkey reverse-index cache."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from portfolio.app import create_app
from portfolio.infrastructure.cache.watchlist_cache import ValkeyWatchlistCache

from tests.integration.helpers import INTEGRATION_TENANT_ID, INTEGRATION_USER_ID

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _make_cache_with_fakeredis() -> ValkeyWatchlistCache:  # type: ignore[return]
    """Build a ValkeyWatchlistCache backed by an in-process FakeRedis."""
    fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = ValkeyClient.__new__(ValkeyClient)
    client._redis = fake_redis
    return ValkeyWatchlistCache(client=client, ttl=60)


@pytest.fixture(scope="function")
async def cache_client(postgres_container: str):  # type: ignore[no-untyped-def]
    """Integration client that uses a fake Valkey cache (no real Valkey needed).

    Seeds INTEGRATION_TENANT_ID and INTEGRATION_USER_ID into the DB so that routes
    which read tenant_id/user_id from request.state (JWT, F-CRIT-001) find valid rows.
    """
    import os

    from portfolio.api.dependencies import get_read_uow, get_uow, get_watchlist_cache
    from portfolio.infrastructure.db.models.tenant import TenantModel
    from portfolio.infrastructure.db.models.user import UserModel
    from portfolio.infrastructure.db.unit_of_work import (
        SqlAlchemyReadOnlyUnitOfWork,
        SqlAlchemyUnitOfWork,
    )
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from tests.integration.helpers import _INTERNAL_HEADERS

    engine = create_async_engine(postgres_container, echo=False)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Seed the integration tenant and user so watchlist routes can resolve state IDs.
    # Use merge() to avoid PK conflict when both tests share the session-scoped DB.
    async with session_factory() as session:
        await session.merge(TenantModel(id=UUID(INTEGRATION_TENANT_ID), name="Integration Tenant"))
        await session.merge(
            UserModel(
                id=UUID(INTEGRATION_USER_ID),
                tenant_id=UUID(INTEGRATION_TENANT_ID),
                email="integration@test.com",
            )
        )
        await session.commit()

    async def _test_uow() -> AsyncGenerator:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            yield uow

    # PLAN-0088: see services/portfolio/tests/conftest.py — same R27 fix.
    async def _test_read_uow() -> AsyncGenerator:
        async with SqlAlchemyReadOnlyUnitOfWork(session_factory) as uow:
            yield uow

    cache = _make_cache_with_fakeredis()

    # Skip RS256 verification — no JWKS endpoint in integration test environment
    os.environ["PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION"] = "true"
    app = create_app()
    app.dependency_overrides[get_uow] = _test_uow
    app.dependency_overrides[get_read_uow] = _test_read_uow
    app.dependency_overrides[get_watchlist_cache] = lambda: cache
    app.state.session_factory = session_factory
    app.state.engine = engine
    app.state.write_factory = session_factory
    app.state.read_factory = session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=_INTERNAL_HEADERS) as ac:
        yield ac, cache

    app.dependency_overrides.clear()
    await engine.dispose()
    os.environ.pop("PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION", None)


async def test_add_member_invalidates_cache(cache_client) -> None:  # type: ignore[no-untyped-def]
    """After add_member, the reverse-index key is absent (was invalidated)."""
    client, cache = cache_client
    # tenant_id and user_id are pre-seeded in cache_client fixture and
    # embedded in the JWT (request.state), so no API calls are needed here.

    # Create watchlist
    resp = await client.post(
        "/api/v1/watchlists",
        json={"name": "RI WL"},
    )
    assert resp.status_code == 201
    wl_id = resp.json()["id"]

    entity_id = uuid4()

    # Pre-populate cache to simulate a stale entry
    await cache.set_user_ids(entity_id, [uuid4()], ttl=60)
    assert await cache.get_user_ids(entity_id) != []

    # Add member — should call invalidate_entity
    resp = await client.post(
        f"/api/v1/watchlists/{wl_id}/members",
        json={"entity_id": str(entity_id), "entity_type": "company"},
    )
    assert resp.status_code == 201

    # Cache key should be gone after invalidation
    assert await cache.get_user_ids(entity_id) == []


async def test_remove_member_invalidates_cache(cache_client) -> None:  # type: ignore[no-untyped-def]
    """After remove_member, the reverse-index key is absent (was invalidated)."""
    client, cache = cache_client
    # tenant_id and user_id are pre-seeded in cache_client fixture and
    # embedded in the JWT (request.state), so no API calls are needed here.

    resp = await client.post(
        "/api/v1/watchlists",
        json={"name": "RI Rm WL"},
    )
    assert resp.status_code == 201
    wl_id = resp.json()["id"]

    entity_id = uuid4()

    # Add member first
    await client.post(
        f"/api/v1/watchlists/{wl_id}/members",
        json={"entity_id": str(entity_id), "entity_type": "company"},
    )

    # Pre-populate cache
    await cache.set_user_ids(entity_id, [uuid4()], ttl=60)
    assert await cache.get_user_ids(entity_id) != []

    # Remove member — should call invalidate_entity
    resp = await client.delete(
        f"/api/v1/watchlists/{wl_id}/members/{entity_id}",
    )
    assert resp.status_code == 204

    # Cache key should be gone
    assert await cache.get_user_ids(entity_id) == []
