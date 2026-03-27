"""Valkey watchlist cache — maintains a SET of watched entity IDs.

The watchlist consumer calls SADD/SREM on entity additions/removals.
Block 5 (routing) calls SISMEMBER to check overlap.

Key: ``nlp:v1:watched_entities`` (configurable via Settings.valkey_watchlist_key).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import redis.asyncio as redis

logger = get_logger(__name__)  # type: ignore[no-any-return]

_VALKEY_UNAVAILABLE_MSG = "valkey_unavailable"


class WatchlistCache:
    """Redis/Valkey SET-backed watchlist entity cache.

    All operations are best-effort — failures log a warning and return a safe
    default rather than propagating (PRD §6.7 Block 5: "best-effort").
    """

    def __init__(self, client: redis.Redis, key: str = "nlp:v1:watched_entities") -> None:  # type: ignore[type-arg]
        self._client = client
        self._key = key

    async def add_entity(self, entity_id: UUID) -> None:
        """SADD entity_id to the watched entities SET."""
        try:
            await self._client.sadd(self._key, str(entity_id))  # type: ignore[misc]
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                _VALKEY_UNAVAILABLE_MSG,
                operation="sadd",
                entity_id=str(entity_id),
                error=str(exc),
            )

    async def remove_entity(self, entity_id: UUID) -> None:
        """SREM entity_id from the watched entities SET."""
        try:
            await self._client.srem(self._key, str(entity_id))  # type: ignore[misc]
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                _VALKEY_UNAVAILABLE_MSG,
                operation="srem",
                entity_id=str(entity_id),
                error=str(exc),
            )

    async def is_watched(self, entity_id: UUID) -> bool:
        """SISMEMBER check — returns False on Valkey unavailability."""
        try:
            return bool(await self._client.sismember(self._key, str(entity_id)))  # type: ignore[misc]
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                _VALKEY_UNAVAILABLE_MSG,
                operation="sismember",
                entity_id=str(entity_id),
                error=str(exc),
            )
            return False

    async def get_all_watched(self) -> frozenset[UUID]:
        """SMEMBERS — return all watched entity IDs as a frozenset.

        Returns empty frozenset on Valkey unavailability (watchlist signal → 0.0).
        """
        try:
            raw: set[bytes] = await self._client.smembers(self._key)  # type: ignore[misc]
            return frozenset(UUID(m.decode() if isinstance(m, bytes) else m) for m in raw)
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                _VALKEY_UNAVAILABLE_MSG,
                operation="smembers",
                error=str(exc),
            )
            return frozenset()
