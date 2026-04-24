"""SymbolTierRepository port — persistence interface for tier assignments."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_ingestion.domain.entities.symbol_tier import SymbolTier, TierLevel


class SymbolTierRepositoryPort(ABC):
    """Persistence port for SymbolTier entities."""

    @abstractmethod
    async def get(self, symbol: str, exchange: str) -> SymbolTier | None:
        """Return the tier for a symbol+exchange pair, or None if not recorded."""

    @abstractmethod
    async def save(self, tier: SymbolTier) -> None:
        """Upsert a SymbolTier (insert or replace on symbol+exchange unique key)."""

    @abstractmethod
    async def get_by_tier(self, tier: TierLevel) -> list[SymbolTier]:
        """Return all symbols currently assigned to the given tier."""
