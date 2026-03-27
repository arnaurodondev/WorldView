"""SQLAlchemy implementation of ProviderBudgetRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from common.ids import new_ulid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.application.ports.repositories import ProviderBudgetRepository
from market_ingestion.domain.entities.provider_budget import ProviderBudget
from market_ingestion.domain.enums import Provider
from market_ingestion.infrastructure.db.models.provider_budget import ProviderBudgetModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _to_domain(row: ProviderBudgetModel) -> ProviderBudget:
    return ProviderBudget(
        id=row.id,
        provider=Provider(row.provider),
        burst_capacity=float(row.max_tokens),
        refill_rate=row.refill_rate_per_second,
        tokens=row.current_tokens,
        last_refill_at=row.last_refill_at,
        updated_at=row.updated_at,
    )


class SqlaProviderBudgetRepository(ProviderBudgetRepository):
    """SQLAlchemy-backed ProviderBudgetRepository."""

    def __init__(self, write_session: AsyncSession, read_session: AsyncSession) -> None:
        self._w = write_session
        self._r = read_session

    async def get(self, provider: Provider) -> ProviderBudget | None:
        stmt = select(ProviderBudgetModel).where(ProviderBudgetModel.provider == provider.value)
        row = (await self._r.execute(stmt)).scalar_one_or_none()
        return _to_domain(row) if row else None

    async def get_or_create(self, provider: Provider) -> ProviderBudget:
        defaults = ProviderBudget.for_eodhd() if provider == Provider.EODHD else ProviderBudget(provider=provider)
        now = utc_now()
        stmt = (
            pg_insert(ProviderBudgetModel)
            .values(
                id=new_ulid(),
                provider=provider.value,
                max_tokens=int(defaults.burst_capacity),
                current_tokens=defaults.tokens,
                refill_rate_per_second=defaults.refill_rate,
                last_refill_at=now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["provider"])
        )
        await self._w.execute(stmt)
        existing = await self.get(provider)
        if existing:
            return existing
        return defaults

    async def save(self, budget: ProviderBudget) -> None:
        now = utc_now()
        stmt = (
            update(ProviderBudgetModel)
            .where(ProviderBudgetModel.provider == budget.provider.value)
            .values(
                current_tokens=budget.tokens,
                last_refill_at=budget.last_refill_at,
                updated_at=now,
            )
        )
        await self._w.execute(stmt)

    async def list_all(self) -> list[ProviderBudget]:
        rows = (await self._r.execute(select(ProviderBudgetModel))).scalars().all()
        return [_to_domain(row) for row in rows]
