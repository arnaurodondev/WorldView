"""ChunkCachePort — async read/write interface for chunk and summary caching (T-A-3-01).

Implemented by ValkeyChunkCacheAdapter in the infrastructure layer.
The port stores arbitrary JSON-serialisable dicts so the application layer
is not coupled to any specific serialisation or storage technology.

Key taxonomy (Valkey):
    Chunks:    s8:ctx:chunks:{thread_id}:{turn_num}   TTL 4 h
    Summaries: s8:ctx:summary:{thread_id}:{turn_num}  TTL 24 h
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChunkCachePort(Protocol):
    """Read/write cache interface for conversation chunk and summary storage."""

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return the dict stored at *key*, or ``None`` on a cache miss."""
        ...

    async def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        """Persist *value* at *key* with a time-to-live of *ttl* seconds."""
        ...
