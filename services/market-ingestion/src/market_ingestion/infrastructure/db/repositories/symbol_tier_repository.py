"""SQLAlchemy implementation of SymbolTierRepositoryPort."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from market_ingestion.application.ports.symbol_tier_repository import SymbolTierRepositoryPort
from market_ingestion.domain.entities.symbol_tier import SymbolTier, TierLevel
from market_ingestion.infrastructure.db.models.symbol_tier import SymbolTierModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _to_domain(row: SymbolTierModel) -> SymbolTier:
    return SymbolTier(
        id=row.id,
        symbol=row.symbol,
        exchange=row.exchange,
        tier=TierLevel(row.tier),
        tier_source=row.tier_source,
        assigned_at=row.assigned_at,
        last_user_refresh_at=row.last_user_refresh_at,
        created_at=row.created_at,
    )


class SqlaSymbolTierRepository(SymbolTierRepositoryPort):
    """SQLAlchemy-backed SymbolTierRepositoryPort."""

    def __init__(self, write_session: AsyncSession, read_session: AsyncSession) -> None:
        self._w = write_session
        self._r = read_session

    async def get(self, symbol: str, exchange: str) -> SymbolTier | None:
        stmt = (
            select(SymbolTierModel)
            .where(SymbolTierModel.symbol == symbol, SymbolTierModel.exchange == exchange)
            .limit(1)
        )
        row = (await self._r.execute(stmt)).scalar_one_or_none()
        return _to_domain(row) if row else None

    async def save(self, tier: SymbolTier) -> None:
        """Upsert using ON CONFLICT (symbol, exchange) DO UPDATE.

        This ensures idempotent saves — calling save() twice with the same
        symbol+exchange replaces the row rather than raising an integrity error.
        """
        stmt = (
            pg_insert(SymbolTierModel)
            .values(
                id=tier.id,
                symbol=tier.symbol,
                exchange=tier.exchange,
                tier=tier.tier.value,
                tier_source=tier.tier_source,
                assigned_at=tier.assigned_at,
                last_user_refresh_at=tier.last_user_refresh_at,
                created_at=tier.created_at,
            )
            .on_conflict_do_update(
                constraint="uq_symbol_tiers_symbol_exchange",
                set_={
                    "tier": tier.tier.value,
                    "tier_source": tier.tier_source,
                    "assigned_at": tier.assigned_at,
                    "last_user_refresh_at": tier.last_user_refresh_at,
                },
            )
        )
        await self._w.execute(stmt)

    async def get_by_tier(self, tier: TierLevel) -> list[SymbolTier]:
        stmt = select(SymbolTierModel).where(SymbolTierModel.tier == tier.value)
        rows = (await self._r.execute(stmt)).scalars().all()
        return [_to_domain(row) for row in rows]
