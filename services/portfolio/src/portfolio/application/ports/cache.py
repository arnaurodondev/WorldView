"""Cache port for watchlist intelligence layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


class WatchlistCachePort(ABC):
    """Abstract cache for the watchlist reverse-index (entity → user_ids)."""

    @abstractmethod
    async def get_user_ids(self, entity_id: UUID) -> list[UUID]: ...

    @abstractmethod
    async def invalidate_entity(self, entity_id: UUID) -> None: ...

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
