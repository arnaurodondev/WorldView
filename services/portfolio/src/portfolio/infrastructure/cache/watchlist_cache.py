"""Valkey-backed watchlist reverse-index cache implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from portfolio.application.ports.cache import WatchlistCachePort

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]


def _key(entity_id: UUID) -> str:
    return f"pf:v1:watchlist:entity:{entity_id}"


class ValkeyWatchlistCache(WatchlistCachePort):
    """Reverse-index cache: entity_id → set of user_ids.

    Uses a Redis Set per entity so that membership ops are O(1).
    Key format: ``pf:v1:watchlist:entity:{entity_id}``
    """

    def __init__(self, client: ValkeyClient, ttl: int = 300) -> None:
        self._client = client
        self._ttl = ttl

    async def get_user_ids(self, entity_id: UUID) -> list[UUID]:
        """Return all user_ids tracking *entity_id*; empty list on cache miss."""
        members: set[str] = await self._client._redis.smembers(_key(entity_id))
        if not members:
            return []
        return [UUID(m) for m in members]

    async def invalidate_entity(self, entity_id: UUID) -> None:
        """Delete the reverse-index key for *entity_id* (cache invalidation)."""
        await self._client._redis.delete(_key(entity_id))

    async def set_user_ids(self, entity_id: UUID, user_ids: list[UUID], ttl: int | None = None) -> None:
        """Atomically replace the user set for *entity_id* and set TTL."""
        key = _key(entity_id)
        effective_ttl = ttl if ttl is not None else self._ttl
        await self._client._redis.delete(key)
        if user_ids:
            await self._client._redis.sadd(key, *[str(uid) for uid in user_ids])
            await self._client._redis.expire(key, effective_ttl)
