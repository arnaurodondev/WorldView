"""Watchlist cache — cache-aside pattern backed by Valkey.

Key pattern: ``s10:v1:watchlist:by_entity:{entity_id}``
TTL: configurable (default 300s).

On cache miss, falls through to S1Client.  S1 failures return ``[]``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

from alert.infrastructure.metrics.prometheus import s10_s1_lookup_failed_total

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from alert.infrastructure.clients.s1_client import S1Client, WatcherInfo

logger = structlog.get_logger(__name__)

_KEY_PREFIX = "s10:v1:watchlist:by_entity"


class WatchlistCache:
    """Cache-aside wrapper for S1 watchlist lookups.

    Usage::

        cache = WatchlistCache(valkey, s1_client, ttl=300)
        watchers = await cache.get_watchers(entity_id)
    """

    def __init__(self, valkey: Redis, s1_client: S1Client, ttl: int = 300) -> None:  # type: ignore[type-arg]
        self._valkey = valkey
        self._s1 = s1_client
        self._ttl = ttl

    async def get_watchers(self, entity_id: str) -> list[WatcherInfo]:
        """Return watchers for an entity — from cache if available, else S1."""
        key = f"{_KEY_PREFIX}:{entity_id}"

        # --- cache hit ---
        cached = await self._safe_get(key)
        if cached is not None:
            logger.debug("watchlist_cache_hit", entity_id=entity_id)
            return self._deserialise(cached)

        # --- cache miss → S1 ---
        logger.debug("watchlist_cache_miss", entity_id=entity_id)
        watchers, ok = await self._s1.get_watchers_by_entity(entity_id)

        if not ok:
            s10_s1_lookup_failed_total.inc()
            logger.warning("watchlist_s1_unavailable", entity_id=entity_id)  # type: ignore[no-any-return]
        elif watchers:
            await self._safe_set(key, self._serialise(watchers))

        return watchers

    async def invalidate(self, entity_id: str) -> None:
        """Remove cached entry for an entity (e.g. on watchlist update)."""
        key = f"{_KEY_PREFIX}:{entity_id}"
        try:
            await self._valkey.delete(key)
        except Exception:
            logger.warning("watchlist_cache_invalidate_failed", entity_id=entity_id, exc_info=True)

    # ----- internal helpers -----

    async def _safe_get(self, key: str) -> str | None:
        try:
            result = await self._valkey.get(key)
            if isinstance(result, bytes):
                return result.decode()
            return result if isinstance(result, str) else None
        except Exception:
            logger.warning("watchlist_cache_get_failed", key=key, exc_info=True)
            return None

    async def _safe_set(self, key: str, value: str) -> None:
        try:
            await self._valkey.set(key, value, ex=self._ttl)
        except Exception:
            logger.warning("watchlist_cache_set_failed", key=key, exc_info=True)

    @staticmethod
    def _serialise(watchers: list[WatcherInfo]) -> str:
        return json.dumps(
            [{"user_id": w.user_id, "watchlist_id": w.watchlist_id, "alert_types": w.alert_types} for w in watchers]
        )

    @staticmethod
    def _deserialise(raw: str) -> list[WatcherInfo]:
        from alert.infrastructure.clients.s1_client import WatcherInfo

        items = json.loads(raw)
        return [
            WatcherInfo(
                user_id=item["user_id"],
                watchlist_id=item["watchlist_id"],
                alert_types=item.get("alert_types", []),
            )
            for item in items
        ]
