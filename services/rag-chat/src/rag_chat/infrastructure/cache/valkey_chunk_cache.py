"""ValkeyChunkCacheAdapter — Valkey-backed ChunkCachePort (T-A-3-02).

Reads and writes chunk / turn-summary payloads as JSON using ValkeyClient's
built-in ``get_json`` / ``set_json`` helpers.

TTL constants are exposed as module-level values so they can be imported by
the ContextManager and used when building Valkey key payloads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

#: TTL for cached retrieval chunks (4 hours).
CHUNK_TTL: int = 4 * 3600
#: TTL for LLM-generated turn summaries (24 hours).
SUMMARY_TTL: int = 24 * 3600


class ValkeyChunkCacheAdapter:
    """Store and retrieve serialised chunk/summary payloads from Valkey.

    Args:
        valkey: A :class:`~messaging.valkey.client.ValkeyClient` instance.
    """

    def __init__(self, valkey: ValkeyClient) -> None:
        self._valkey = valkey

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached dict or ``None`` on a miss."""
        return await self._valkey.get_json(key)  # type: ignore[no-any-return]

    async def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        """Persist *value* as JSON under *key* with *ttl* seconds expiry."""
        await self._valkey.set_json(key, value, ttl=ttl)
