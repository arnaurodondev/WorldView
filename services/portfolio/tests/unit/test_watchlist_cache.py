"""Unit tests for ValkeyWatchlistCache using fakeredis."""

from __future__ import annotations

from uuid import uuid4

import pytest
from portfolio.infrastructure.cache.watchlist_cache import ValkeyWatchlistCache

pytestmark = pytest.mark.unit


def _make_cache(fake_redis) -> ValkeyWatchlistCache:  # type: ignore[no-untyped-def]
    """Build a ValkeyWatchlistCache backed by a FakeRedis instance."""
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

    client = ValkeyClient.__new__(ValkeyClient)
    client._redis = fake_redis
    return ValkeyWatchlistCache(client=client, ttl=60)


@pytest.fixture
def fake_redis():  # type: ignore[no-untyped-def]
    fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_invalidate_entity_deletes_key(fake_redis) -> None:
    """invalidate_entity removes the reverse-index key."""
    cache = _make_cache(fake_redis)
    entity_id = uuid4()
    user_id = uuid4()

    # Pre-populate
    await cache.set_user_ids(entity_id, [user_id], ttl=60)
    assert await fake_redis.exists(f"pf:v1:watchlist:entity:{entity_id}")

    await cache.invalidate_entity(entity_id)
    assert not await fake_redis.exists(f"pf:v1:watchlist:entity:{entity_id}")


@pytest.mark.asyncio
async def test_set_user_ids_populates_set(fake_redis) -> None:
    """set_user_ids stores user UUIDs in the Redis Set."""
    cache = _make_cache(fake_redis)
    entity_id = uuid4()
    user1, user2 = uuid4(), uuid4()

    await cache.set_user_ids(entity_id, [user1, user2], ttl=60)
    members = await fake_redis.smembers(f"pf:v1:watchlist:entity:{entity_id}")
    assert str(user1) in members
    assert str(user2) in members


@pytest.mark.asyncio
async def test_get_user_ids_returns_list_from_set(fake_redis) -> None:
    """get_user_ids returns all user UUIDs from the Redis Set."""
    cache = _make_cache(fake_redis)
    entity_id = uuid4()
    user1, user2 = uuid4(), uuid4()

    await cache.set_user_ids(entity_id, [user1, user2], ttl=60)
    result = await cache.get_user_ids(entity_id)

    assert set(result) == {user1, user2}


@pytest.mark.asyncio
async def test_get_user_ids_returns_empty_on_miss(fake_redis) -> None:
    """get_user_ids returns [] when the key does not exist."""
    cache = _make_cache(fake_redis)
    entity_id = uuid4()

    result = await cache.get_user_ids(entity_id)
    assert result == []
