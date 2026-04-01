"""SQLAlchemy implementation of PollingPolicyRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import or_, select, update

from market_ingestion.application.ports.repositories import PollingPolicyRepository
from market_ingestion.domain.entities.polling_policy import PollingPolicy
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.infrastructure.db.models.polling_policy import PollingPolicyModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _to_domain(row: PollingPolicyModel) -> PollingPolicy:
    return PollingPolicy(
        id=row.id,
        provider=Provider(row.provider),
        dataset_type=DatasetType(row.dataset_type),
        symbol=row.symbol,
        exchange=row.exchange,
        timeframe=row.timeframe,
        base_interval_seconds=float(row.base_interval_sec),
        k=row.adaptive_k,
        priority=row.priority,
        is_enabled=row.enabled,
        backfill_enabled=row.backfill_enabled,
        backfill_days=row.backfill_chunk_days,
        backfill_start_date=row.backfill_start_date,
        created_at=row.created_at,
    )


class SqlaPollingPolicyRepository(PollingPolicyRepository):
    """SQLAlchemy-backed PollingPolicyRepository."""

    def __init__(self, write_session: AsyncSession, read_session: AsyncSession) -> None:
        self._w = write_session
        self._r = read_session

    async def get(self, policy_id: str) -> PollingPolicy | None:
        row = await self._r.get(PollingPolicyModel, policy_id)
        return _to_domain(row) if row else None

    async def list_enabled(self) -> list[PollingPolicy]:
        stmt = (
            select(PollingPolicyModel)
            .where(PollingPolicyModel.enabled.is_(True))
            .order_by(PollingPolicyModel.priority.desc())
        )
        rows = (await self._r.execute(stmt)).scalars().all()
        return [_to_domain(row) for row in rows]

    async def find_matching(
        self,
        *,
        provider: Provider,
        dataset_type: DatasetType,
        symbol: str | None = None,
        exchange: str | None = None,
        timeframe: str | None = None,
        variant: str | None = None,
    ) -> PollingPolicy | None:
        """Find the most specific matching policy (most-specific-wins).

        Tries symbol-specific first, then wildcard (symbol IS NULL).
        For exchange, timeframe, and variant: a NULL column value acts as a
        wildcard that matches any incoming value; a non-NULL column value must
        match exactly.
        """
        for sym in (symbol, None):
            filters = [
                PollingPolicyModel.provider == provider.value,
                PollingPolicyModel.dataset_type == dataset_type.value,
                PollingPolicyModel.enabled.is_(True),
                PollingPolicyModel.symbol == sym,
            ]
            if exchange is not None:
                filters.append(or_(PollingPolicyModel.exchange == exchange, PollingPolicyModel.exchange.is_(None)))
            if timeframe is not None:
                filters.append(or_(PollingPolicyModel.timeframe == timeframe, PollingPolicyModel.timeframe.is_(None)))
            if variant is not None:
                filters.append(
                    or_(PollingPolicyModel.dataset_variant == variant, PollingPolicyModel.dataset_variant.is_(None))
                )
            stmt = select(PollingPolicyModel).where(*filters).order_by(PollingPolicyModel.priority.desc()).limit(1)
            row = (await self._r.execute(stmt)).scalar_one_or_none()
            if row is not None:
                return _to_domain(row)
        return None

    async def add(self, policy: PollingPolicy) -> None:
        row = PollingPolicyModel(
            id=policy.id,
            provider=policy.provider.value,
            dataset_type=policy.dataset_type.value,
            symbol=policy.symbol,
            exchange=policy.exchange,
            timeframe=policy.timeframe,
            base_interval_sec=int(policy.base_interval_seconds),
            adaptive_k=policy.k,
            priority=policy.priority,
            enabled=policy.is_enabled,
            backfill_enabled=policy.backfill_enabled,
            backfill_start_date=policy.backfill_start_date,
            backfill_chunk_days=policy.backfill_days,
            created_at=policy.created_at,
        )
        self._w.add(row)

    async def save(self, policy: PollingPolicy) -> None:
        stmt = (
            update(PollingPolicyModel)
            .where(PollingPolicyModel.id == policy.id)
            .values(
                enabled=policy.is_enabled,
                priority=policy.priority,
                base_interval_sec=int(policy.base_interval_seconds),
                adaptive_k=policy.k,
                backfill_enabled=policy.backfill_enabled,
                backfill_start_date=policy.backfill_start_date,
                backfill_chunk_days=policy.backfill_days,
            )
        )
        await self._w.execute(stmt)
