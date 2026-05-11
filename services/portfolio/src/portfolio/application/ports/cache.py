"""Cache port for watchlist intelligence layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class WatchlistCachePort(ABC):
    """Abstract cache for the watchlist reverse-index (entity → user_ids).

    Implementations MUST be fail-open: cache errors should be logged and
    counted (via Prometheus) but never raised.  This preserves the contract
    that a Valkey outage cannot break the primary write path.
    """

    @abstractmethod
    async def get_user_ids(self, entity_id: UUID) -> list[UUID]: ...

    @abstractmethod
    async def invalidate_entity(self, entity_id: UUID) -> None:
        """Remove cached entries for *entity_id*. Must not raise on cache failure."""
        ...

    @abstractmethod
    async def set_user_ids(self, entity_id: UUID, user_ids: list[UUID], ttl: int) -> None: ...


class NoOpWatchlistCache(WatchlistCachePort):
    """No-op implementation — used in wave-01 until Valkey wiring is added in wave-02."""

    async def get_user_ids(self, entity_id: UUID) -> list[UUID]:
        return []

    async def invalidate_entity(self, entity_id: UUID) -> None:
        pass

    async def set_user_ids(self, entity_id: UUID, user_ids: list[UUID], ttl: int) -> None:
        pass
