"""Integration tests for the watchlist Valkey reverse-index cache."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from portfolio.app import create_app
from portfolio.infrastructure.cache.watchlist_cache import ValkeyWatchlistCache

from tests.integration.helpers import make_tenant, make_user

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
    """Integration client that uses a fake Valkey cache (no real Valkey needed)."""
    from portfolio.api.dependencies import get_uow, get_watchlist_cache
    from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(postgres_container, echo=False)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _test_uow() -> AsyncGenerator:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            yield uow

    cache = _make_cache_with_fakeredis()

    app = create_app()
    app.dependency_overrides[get_uow] = _test_uow
    app.dependency_overrides[get_watchlist_cache] = lambda: cache
    app.state.session_factory = session_factory
    app.state.engine = engine

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, cache

    app.dependency_overrides.clear()
    await engine.dispose()


async def test_add_member_invalidates_cache(cache_client) -> None:  # type: ignore[no-untyped-def]
    """After add_member, the reverse-index key is absent (was invalidated)."""
    client, cache = cache_client
    tenant = await make_tenant(client, name="RITenant")
    user = await make_user(client, tenant["id"], email="ri@test.com")

    # Create watchlist
    resp = await client.post(
        "/api/v1/watchlists",
        json={"name": "RI WL"},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
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
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 201

    # Cache key should be gone after invalidation
    assert await cache.get_user_ids(entity_id) == []


async def test_remove_member_invalidates_cache(cache_client) -> None:  # type: ignore[no-untyped-def]
    """After remove_member, the reverse-index key is absent (was invalidated)."""
    client, cache = cache_client
    tenant = await make_tenant(client, name="RIRmTenant")
    user = await make_user(client, tenant["id"], email="rirm@test.com")

    resp = await client.post(
        "/api/v1/watchlists",
        json={"name": "RI Rm WL"},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 201
    wl_id = resp.json()["id"]

    entity_id = uuid4()

    # Add member first
    await client.post(
        f"/api/v1/watchlists/{wl_id}/members",
        json={"entity_id": str(entity_id), "entity_type": "company"},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )

    # Pre-populate cache
    await cache.set_user_ids(entity_id, [uuid4()], ttl=60)
    assert await cache.get_user_ids(entity_id) != []

    # Remove member — should call invalidate_entity
    resp = await client.delete(
        f"/api/v1/watchlists/{wl_id}/members/{entity_id}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 204

    # Cache key should be gone
    assert await cache.get_user_ids(entity_id) == []
