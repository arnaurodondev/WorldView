"""LLM completion cache backed by Valkey (T-E-1-02).

Caches full completion responses keyed by a SHA-256 hash of the sanitised
message and thread_id. TTL is 24 hours.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    import redis.asyncio as aioredis

_TTL_SECONDS = 86_400  # 24 hours


def _cache_key(message: str, thread_id: UUID | None) -> str:
    raw = f"{message}:{thread_id}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"rag:v1:completion:{digest}"


class CompletionCache:
    """Cache LLM completion responses to avoid redundant inference.

    Args:
        valkey: An async Redis/Valkey client (``redis.asyncio.Redis``).
    """

    def __init__(self, valkey: aioredis.Redis) -> None:  # type: ignore[type-arg]
        self._valkey = valkey

    async def get(self, message: str, thread_id: UUID | None) -> dict | None:  # type: ignore[type-arg]
        """Return the cached response dict or *None* on a cache miss."""
        key = _cache_key(message, thread_id)
        data: bytes | None = await self._valkey.get(key)
        if data is None:
            return None
        return json.loads(data)  # type: ignore[no-any-return]

    async def set(self, message: str, thread_id: UUID | None, response: dict) -> None:  # type: ignore[type-arg]
        """Store *response* under *message* + *thread_id* for 24 hours."""
        key = _cache_key(message, thread_id)
        await self._valkey.setex(key, _TTL_SECONDS, json.dumps(response))
