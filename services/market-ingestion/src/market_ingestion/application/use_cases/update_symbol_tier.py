"""UpdateSymbolTierUseCase — assigns or updates the cadence tier for a symbol+exchange pair.

Called by:
- Portfolio sync (S1 events) → T0 for held symbols
- Watchlist changes → T1 for watched symbols
- Screener queries → T3 for newly-seen comparison symbols
- Inactivity cleanup → T4 for symbols not accessed in 30 days

The tier assignment is persisted to the symbol_tiers table and used by
ScheduleDueTasksUseCase to apply the correct cadence multiplier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from market_ingestion.domain.entities.symbol_tier import SymbolTier, TierLevel

if TYPE_CHECKING:
    from market_ingestion.application.ports.unit_of_work import UnitOfWork

from common.time import utc_now  # type: ignore[import-untyped]


@dataclass
class TierAssignmentResult:
    """Result of a tier assignment operation."""

    symbol: str
    exchange: str
    previous_tier: TierLevel | None
    new_tier: TierLevel
    changed: bool


class UpdateSymbolTierUseCase:
    """Assign or promote/demote a symbol to a given cadence tier.

    Idempotent: calling with the same tier twice is a no-op (changed=False).
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        symbol: str,
        exchange: str,
        tier: TierLevel,
        source: str = "system",
    ) -> TierAssignmentResult:
        async with self._uow:
            existing = await self._uow.symbol_tiers.get(symbol, exchange)
            previous = existing.tier if existing else None

            if existing is None:
                tier_obj = SymbolTier(symbol=symbol, exchange=exchange, tier=tier, tier_source=source)
                await self._uow.symbol_tiers.save(tier_obj)
                changed = True
            else:
                changed = existing.tier != tier
                if changed:
                    existing.tier = tier
                    existing.tier_source = source
                    existing.assigned_at = utc_now()
                    await self._uow.symbol_tiers.save(existing)

            await self._uow.commit()

        return TierAssignmentResult(
            symbol=symbol,
            exchange=exchange,
            previous_tier=previous,
            new_tier=tier,
            changed=changed,
        )
