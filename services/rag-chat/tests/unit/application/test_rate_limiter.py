"""Unit tests for RateLimiter (T-E-1-02).

Uses fakeredis for an in-process Valkey simulation.
"""

from __future__ import annotations

from uuid import UUID

import fakeredis.aioredis
import pytest
from rag_chat.application.caching.rate_limiter import RateLimiter
from rag_chat.domain.errors import RateLimitExceededError

pytestmark = pytest.mark.unit

_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture()
def fake_valkey() -> fakeredis.aioredis.FakeRedis:
    # decode_responses=True matches ValkeyClient default
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


class TestRateLimiter:
    async def test_rate_limiter_allows_10_per_min(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """10 requests within the window → all succeed."""
        limiter = RateLimiter(fake_valkey, limit=10)
        for _ in range(10):
            await limiter.check_and_increment(_TENANT_ID)
        # No exception raised — test passes

    async def test_rate_limiter_blocks_11th(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """11th request in the same 60-second window → RateLimitExceededError."""
        limiter = RateLimiter(fake_valkey, limit=10)
        for _ in range(10):
            await limiter.check_and_increment(_TENANT_ID)
        with pytest.raises(RateLimitExceededError):
            await limiter.check_and_increment(_TENANT_ID)

    async def test_rate_limiter_different_tenants_isolated(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """Each tenant has an independent window — one tenant's limit does not affect another."""
        tenant_a = UUID("00000000-0000-0000-0000-000000000001")
        tenant_b = UUID("00000000-0000-0000-0000-000000000002")
        limiter = RateLimiter(fake_valkey, limit=1)

        await limiter.check_and_increment(tenant_a)
        # Tenant B should not be affected by tenant A reaching its limit
        await limiter.check_and_increment(tenant_b)

    async def test_rate_limiter_uses_sliding_window_key_format(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """Rate limiter stores data under the expected Valkey key pattern."""
        limiter = RateLimiter(fake_valkey, limit=10)
        await limiter.check_and_increment(_TENANT_ID)
        expected_key = f"rag:v1:rl:{_TENANT_ID}"
        assert await fake_valkey.exists(expected_key)

    async def test_rate_limiter_raises_on_exceeded(self, fake_valkey: fakeredis.aioredis.FakeRedis) -> None:
        """RateLimitExceededError is raised with a descriptive message."""
        limiter = RateLimiter(fake_valkey, limit=2)
        await limiter.check_and_increment(_TENANT_ID)
        await limiter.check_and_increment(_TENANT_ID)
        with pytest.raises(RateLimitExceededError, match="Rate limit exceeded"):
            await limiter.check_and_increment(_TENANT_ID)
