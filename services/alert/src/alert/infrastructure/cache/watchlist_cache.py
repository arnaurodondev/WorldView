"""Watchlist cache — cache-aside pattern backed by Valkey.

Key pattern: ``s10:v1:watchlist:by_entity:{entity_id}``
TTL: configurable (default 300s).

On cache miss, falls through to S1Client.  S1 failures return ``[]``.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from typing import TYPE_CHECKING

import structlog

from alert.infrastructure.metrics.prometheus import s10_s1_lookup_failed_total

if TYPE_CHECKING:
    # IG-MSG-002: use the messaging Valkey client, never raw redis. The injected
    # object is a ValkeyClient (get/set(ex=)/delete-compatible); this is type-only.
    from alert.infrastructure.clients.s1_client import S1Client, WatcherInfo
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)

_KEY_PREFIX = "s10:v1:watchlist:by_entity"

# ── Issue 4 / Fix B — in-process micro-cache (throughput) ─────────────────────
# The intelligence consumer drained at ~3 msg/min against a 22k backlog because
# every message did a serial watchlist lookup that, when Valkey was timing out
# (the failure window), fell through to a blocking S1 REST call. During a burst
# drain the SAME entity recurs many times within seconds, so an in-process
# layer in front of Valkey collapses those repeats to a single lookup and
# removes the Valkey round-trip on hits (and is immune to Valkey timeouts).
#
# Semantics are preserved by a deliberately SHORT TTL: invalidation is
# cross-process (the separate watchlist-consumer deletes the *Valkey* key on a
# `portfolio.watchlist.updated.v1` event), which this in-process layer cannot
# observe directly. A short TTL bounds staleness to `_LOCAL_TTL_SECONDS` after a
# watchlist change — far below the 300s Valkey TTL that already governs how
# fresh these lookups are — while still eliminating the per-message serial cost
# that caused the stall. `_LOCAL_MAX_ENTRIES` bounds memory (LRU eviction).
_LOCAL_TTL_SECONDS: float = 10.0
_LOCAL_MAX_ENTRIES: int = 4_096


class WatchlistCache:
    """Cache-aside wrapper for S1 watchlist lookups.

    Usage::

        cache = WatchlistCache(valkey, s1_client, ttl=300)
        watchers = await cache.get_watchers(entity_id)
    """

    def __init__(
        self,
        valkey: ValkeyClient,
        s1_client: S1Client,
        ttl: int = 300,
        *,
        local_ttl_seconds: float = _LOCAL_TTL_SECONDS,
        local_max_entries: int = _LOCAL_MAX_ENTRIES,
    ) -> None:
        self._valkey = valkey
        self._s1 = s1_client
        self._ttl = ttl
        # In-process TTL+LRU micro-cache: entity_id -> (expiry_monotonic, watchers).
        # OrderedDict gives O(1) move-to-end for LRU recency tracking.
        self._local_ttl = local_ttl_seconds
        self._local_max = local_max_entries
        self._local: OrderedDict[str, tuple[float, list[WatcherInfo]]] = OrderedDict()

    def _local_get(self, entity_id: str) -> list[WatcherInfo] | None:
        """Return a non-expired in-process hit, or None. Evicts on expiry."""
        entry = self._local.get(entity_id)
        if entry is None:
            return None
        expiry, watchers = entry
        if time.monotonic() >= expiry:
            # Expired — drop it so the next caller refreshes from Valkey/S1.
            self._local.pop(entity_id, None)
            return None
        # Mark as most-recently-used for LRU.
        self._local.move_to_end(entity_id)
        return watchers

    def _local_put(self, entity_id: str, watchers: list[WatcherInfo]) -> None:
        """Store a result in the in-process cache, evicting LRU if over capacity."""
        self._local[entity_id] = (time.monotonic() + self._local_ttl, watchers)
        self._local.move_to_end(entity_id)
        while len(self._local) > self._local_max:
            self._local.popitem(last=False)  # evict least-recently-used

    async def get_watchers(self, entity_id: str) -> list[WatcherInfo]:
        """Return watchers for an entity — from cache if available, else S1."""
        # --- in-process micro-cache hit (Fix B): no network round-trip ---
        local = self._local_get(entity_id)
        if local is not None:
            logger.debug("watchlist_local_cache_hit", entity_id=entity_id)
            return local

        key = f"{_KEY_PREFIX}:{entity_id}"

        # --- Valkey cache hit ---
        cached = await self._safe_get(key)
        if cached is not None:
            logger.debug("watchlist_cache_hit", entity_id=entity_id)
            watchers = self._deserialise(cached)
            self._local_put(entity_id, watchers)
            return watchers

        # --- cache miss → S1 ---
        logger.debug("watchlist_cache_miss", entity_id=entity_id)
        watchers, ok = await self._s1.get_watchers_by_entity(entity_id)

        if not ok:
            s10_s1_lookup_failed_total.inc()
            logger.warning("watchlist_s1_unavailable", entity_id=entity_id)  # type: ignore[no-any-return]
            # Do NOT populate the local cache on an S1 failure — caching an
            # empty/failed result would suppress alerts until the TTL expires.
            return watchers
        if watchers:
            await self._safe_set(key, self._serialise(watchers))
        # Cache the authoritative S1 result (including a confirmed-empty list,
        # which is a valid "no watchers" answer) for the short local TTL.
        self._local_put(entity_id, watchers)

        return watchers

    async def invalidate(self, entity_id: str) -> None:
        """Remove cached entry for an entity (e.g. on watchlist update)."""
        # Drop the in-process copy too. NOTE: invalidation events are consumed by
        # the separate watchlist-consumer process, so this only clears THIS
        # process's local cache; the intelligence-consumer's local copy still
        # ages out via the short `_local_ttl`. That bounded staleness is the
        # documented trade-off in Fix B.
        self._local.pop(entity_id, None)
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
            [{"user_id": w.user_id, "watchlist_id": w.watchlist_id, "alert_types": w.alert_types} for w in watchers],
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
