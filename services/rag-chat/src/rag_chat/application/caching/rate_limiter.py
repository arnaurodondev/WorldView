"""Sliding-window rate limiter backed by Valkey (T-E-1-02).

Uses a sorted set per tenant to track request timestamps within a 60-second
rolling window. All operations are pipelined (non-transactional) — acceptable
for rate limiting where occasional off-by-one is preferable to blocking calls.
"""

from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING

from rag_chat.domain.errors import RateLimitExceededError

if TYPE_CHECKING:
    from uuid import UUID

    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

_WINDOW_SECONDS = 60


class RateLimiter:
    """Per-tenant sliding-window rate limiter.

    Args:
        valkey: A :class:`~messaging.valkey.client.ValkeyClient` instance.
        limit:  Maximum requests allowed within the 60-second window.
    """

    def __init__(self, valkey: ValkeyClient, limit: int = 10) -> None:
        self._valkey = valkey
        self._limit = limit

    async def check_and_increment(self, tenant_id: UUID) -> None:
        """Record a request for *tenant_id* and raise if the limit is exceeded.

        Raises:
            RateLimitExceededError: if the tenant has exceeded *limit* requests
                in the past 60 seconds.
        """
        key = f"rag:v1:rl:{tenant_id}"
        now = time.time()
        cutoff = now - _WINDOW_SECONDS
        # Unique member so two simultaneous requests at identical timestamps coexist
        member = f"{now:.6f}:{secrets.token_hex(4)}"

        async with self._valkey.pipeline(transaction=False) as pipe:
            pipe.zadd(key, {member: now})
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
            pipe.expire(key, _WINDOW_SECONDS)
            results = await pipe.execute()

        count: int = results[2]
        if count > self._limit:
            raise RateLimitExceededError(
                f"Rate limit exceeded: {count} requests in the last {_WINDOW_SECONDS}s (limit: {self._limit})"
            )
