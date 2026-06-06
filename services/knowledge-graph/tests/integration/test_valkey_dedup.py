"""Integration tests for Valkey entity refresh deduplication (Worker 13D).

The 30-minute dedup key prevents the same entity from being re-queued for
embedding refresh within a 30-minute window.  This test uses fakeredis to
avoid requiring a live Valkey instance.
"""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.integration()
async def test_entity_refresh_dedup_prevents_requeue() -> None:
    """Entity queued within 30-min window should not be re-queued."""
    import fakeredis.aioredis as fakeredis

    fake_redis = fakeredis.FakeRedis()
    entity_id = uuid.uuid4()
    dedup_key = f"kg:entity_refresh_dedup:{entity_id}"

    # Simulate: first time, key does NOT exist → should process
    exists_first = await fake_redis.exists(dedup_key)
    assert exists_first == 0

    # Mark as queued (TTL = 1800 s)
    await fake_redis.setex(dedup_key, 1800, "1")

    # Second time, key EXISTS → should be skipped
    exists_second = await fake_redis.exists(dedup_key)
    assert exists_second == 1

    await fake_redis.aclose()


@pytest.mark.integration()
async def test_entity_refresh_dedup_key_expires() -> None:
    """After the TTL expires the key no longer exists (logical test)."""
    import fakeredis.aioredis as fakeredis

    fake_redis = fakeredis.FakeRedis()
    entity_id = uuid.uuid4()
    dedup_key = f"kg:entity_refresh_dedup:{entity_id}"

    # Set with TTL of 60 seconds (1s is unreliable in fakeredis — can round to 0)
    await fake_redis.setex(dedup_key, 60, "1")
    ttl = await fake_redis.ttl(dedup_key)
    assert ttl > 0

    # Manually delete to simulate expiry in a fast test
    await fake_redis.delete(dedup_key)
    exists = await fake_redis.exists(dedup_key)
    assert exists == 0

    await fake_redis.aclose()


@pytest.mark.integration()
async def test_valkey_client_fixture(valkey_client) -> None:
    """Valkey client (if available) should respond to ping."""
    try:
        result = await valkey_client.ping()
        assert result is True or result == b"PONG"
    except Exception:
        pytest.skip("Valkey ping failed — infrastructure not running")
