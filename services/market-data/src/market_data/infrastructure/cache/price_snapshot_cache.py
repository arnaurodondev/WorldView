"""Cache-aside wrapper for PriceSnapshot data using Valkey.

Key format: ``price_snapshot:v1:{instrument_id}``
TTL:        7200 seconds (2 hours) by default.

The cache stores the full PriceSnapshot serialised as JSON (via to_dict /
from_dict).  All operations fail-open: a Valkey unavailability never
propagates to callers — the service degrades gracefully to DB-only mode.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from contracts.canonical.price_snapshot import PriceSnapshot  # type: ignore[import-untyped]
from market_data.application.ports.cache import PriceSnapshotCachePort
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = get_logger(__name__)

# Cache key namespace and default TTL
_KEY_PREFIX = "price_snapshot:v1"
_DEFAULT_TTL = 7200  # 2 hours — covers a full trading day + overnight


class PriceSnapshotCache(PriceSnapshotCachePort):
    """Valkey cache for resolved PriceSnapshot objects.

    This is an infrastructure concern: it wraps ValkeyClient with
    PriceSnapshot-specific serialisation and a fail-open error policy.

    Key format: ``price_snapshot:v1:{instrument_id}``
    TTL:        7200 s (2 h) — configurable per call.

    Used by:
    - QuotesConsumer (after DB upsert, pre-response) to hot-cache fresh data.
    - price_snapshot router (cache-aside reads for GET /internal/v1/price/*).
    """

    def __init__(self, client: ValkeyClient) -> None:
        self._client = client

    def _key(self, instrument_id: str) -> str:
        """Build the canonical Valkey key for the given instrument."""
        return f"{_KEY_PREFIX}:{instrument_id}"

    async def get(self, instrument_id: str) -> PriceSnapshot | None:
        """Return the cached PriceSnapshot, or None on miss or connection error."""
        key = self._key(instrument_id)
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            # raw is bytes or str depending on Valkey client implementation
            data = json.loads(raw) if isinstance(raw, bytes | str) else raw
            return PriceSnapshot.from_dict(data)
        except Exception:
            # Fail-open: cache unavailability must not degrade the read path
            logger.warning("price_snapshot_cache_unavailable_get", key=key)
            return None

    async def set(
        self,
        instrument_id: str,
        snapshot: PriceSnapshot,
        ttl: int = _DEFAULT_TTL,
    ) -> None:
        """Cache a PriceSnapshot; silently degrades on connection error.

        Args:
            instrument_id: The instrument's UUID string.
            snapshot:      The resolved PriceSnapshot to cache.
            ttl:           Key TTL in seconds (default 7200 = 2 h).
        """
        key = self._key(instrument_id)
        try:
            await self._client.set(key, json.dumps(snapshot.to_dict()), ttl=ttl)
        except Exception:
            logger.warning("price_snapshot_cache_unavailable_set", key=key)

    async def invalidate(self, instrument_id: str) -> None:
        """Delete the cached PriceSnapshot for the given instrument."""
        key = self._key(instrument_id)
        try:
            await self._client.delete(key)
        except Exception:
            logger.warning("price_snapshot_cache_unavailable_invalidate", key=key)
