"""Cache port interfaces for the application layer (R25).

Concrete implementations live in ``market_data.infrastructure.cache``.
The application layer must depend only on these ABCs — never on the
infrastructure implementations directly.
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.api.schemas.quotes import QuoteResponse
    from market_data.domain.entities import ScreenFieldMetadata
    from market_data.domain.price_snapshot import PriceSnapshot


class QuoteCachePort(abc.ABC):
    """Port interface for quote caching (R25).

    The application layer (API routers) must depend on this ABC, not on
    ``QuoteCache`` from the infrastructure layer.  This keeps the API layer
    free from infrastructure imports.
    """

    @abc.abstractmethod
    async def get(self, instrument_id: str) -> QuoteResponse | None:
        """Return the cached QuoteResponse, or ``None`` on cache miss."""

    @abc.abstractmethod
    async def set(self, instrument_id: str, quote: QuoteResponse, ttl: int = 5) -> None:
        """Cache a QuoteResponse with the given TTL in seconds."""

    @abc.abstractmethod
    async def invalidate(self, instrument_id: str) -> None:
        """Remove the cached quote for the given instrument."""

    @abc.abstractmethod
    async def invalidate_many(self, instrument_ids: list[str]) -> None:
        """Remove cached quotes for multiple instruments."""


class PriceSnapshotCachePort(abc.ABC):
    """Port interface for price snapshot caching (R25).

    The API layer must depend on this ABC, not on the infrastructure
    ``PriceSnapshotCache`` directly.  Concrete implementation lives in
    ``market_data.infrastructure.cache.price_snapshot_cache``.
    """

    @abc.abstractmethod
    async def get(self, instrument_id: str) -> PriceSnapshot | None:
        """Return the cached PriceSnapshot, or ``None`` on cache miss or error."""

    @abc.abstractmethod
    async def set(self, instrument_id: str, snapshot: PriceSnapshot, ttl: int = 7200) -> None:
        """Cache a PriceSnapshot with the given TTL in seconds."""

    @abc.abstractmethod
    async def invalidate(self, instrument_id: str) -> None:
        """Delete the cached PriceSnapshot for the given instrument."""


class ScreenFieldsCachePort(abc.ABC):
    """Port interface for screen field metadata caching (PRD-0017 §6.2).

    Backed by Valkey key ``s3:screen:fields:v1``.  The concrete implementation
    lives in ``market_data.infrastructure.cache.screen_fields_cache``.
    """

    VALKEY_KEY = "s3:screen:fields:v1"

    @abc.abstractmethod
    async def get_all(self) -> list[ScreenFieldMetadata] | None:
        """Return the cached field list, or ``None`` on cache miss."""

    @abc.abstractmethod
    async def set_all(self, fields: list[ScreenFieldMetadata]) -> None:
        """Overwrite the cached field list (no TTL — refreshed by background job)."""
