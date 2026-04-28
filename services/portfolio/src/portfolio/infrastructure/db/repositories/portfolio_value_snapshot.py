"""SQLAlchemy implementation of ``PortfolioValueSnapshotRepository`` (PLAN-0046 Wave 4)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from portfolio.application.ports.repositories import PortfolioValueSnapshotRepository
from portfolio.domain.entities.portfolio_value_snapshot import PortfolioValueSnapshot
from portfolio.infrastructure.db.models.portfolio_value_snapshot import PortfolioValueSnapshotModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyPortfolioValueSnapshotRepository(PortfolioValueSnapshotRepository):
    """Postgres-backed repository for the daily value snapshot time-series.

    All writes go through ``upsert`` which uses Postgres' native
    ``INSERT ... ON CONFLICT (portfolio_id, snapshot_date) DO UPDATE``
    so that re-running the snapshot worker for the same ``(portfolio,
    date)`` pair is a true idempotent overwrite — not a duplicate
    insert and not a no-op. We always replace the row because
    re-runs typically happen after a price-data backfill has filled
    in previously-missing OHLCV bars; the second run is the more
    accurate value.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: PortfolioValueSnapshotModel) -> PortfolioValueSnapshot:
        return PortfolioValueSnapshot(
            id=row.id,
            portfolio_id=row.portfolio_id,
            tenant_id=row.tenant_id,
            snapshot_date=row.snapshot_date,
            total_value=row.total_value,
            total_cost=row.total_cost,
            cash_value=row.cash_value,
            created_at=row.created_at,
        )

    async def upsert(self, snapshot: PortfolioValueSnapshot) -> None:
        """Idempotent upsert keyed on ``(portfolio_id, snapshot_date)``.

        WHY ON CONFLICT DO UPDATE (not DO NOTHING): we want re-runs to
        carry the latest computed value. If OHLCV bars were back-filled
        between two worker passes, the second pass produces a more
        accurate value and should overwrite. ``id``/``created_at`` of
        the existing row are preserved by excluding them from
        ``set_``.
        """
        stmt = pg_insert(PortfolioValueSnapshotModel).values(
            id=snapshot.id,
            portfolio_id=snapshot.portfolio_id,
            tenant_id=snapshot.tenant_id,
            snapshot_date=snapshot.snapshot_date,
            total_value=snapshot.total_value,
            total_cost=snapshot.total_cost,
            cash_value=snapshot.cash_value,
            created_at=snapshot.created_at,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_portfolio_value_snapshots_portfolio_date",
            set_={
                "total_value": stmt.excluded.total_value,
                "total_cost": stmt.excluded.total_cost,
                "cash_value": stmt.excluded.cash_value,
                # tenant_id is technically immutable per portfolio but we
                # include it so the row stays consistent if it was ever
                # written with a wrong tenant_id (defensive).
                "tenant_id": stmt.excluded.tenant_id,
            },
        )
        await self._session.execute(stmt)

    async def list_range(
        self,
        portfolio_id: UUID,
        from_date: date,
        to_date: date,
    ) -> list[PortfolioValueSnapshot]:
        """Return snapshots in ``[from_date, to_date]`` inclusive, oldest-first."""
        result = await self._session.execute(
            select(PortfolioValueSnapshotModel)
            .where(
                PortfolioValueSnapshotModel.portfolio_id == portfolio_id,
                PortfolioValueSnapshotModel.snapshot_date >= from_date,
                PortfolioValueSnapshotModel.snapshot_date <= to_date,
            )
            .order_by(PortfolioValueSnapshotModel.snapshot_date.asc()),
        )
        return [self._to_entity(r) for r in result.scalars()]

    async def get_latest(self, portfolio_id: UUID) -> PortfolioValueSnapshot | None:
        """Return the most recent snapshot for the portfolio, or None."""
        result = await self._session.execute(
            select(PortfolioValueSnapshotModel)
            .where(PortfolioValueSnapshotModel.portfolio_id == portfolio_id)
            .order_by(desc(PortfolioValueSnapshotModel.snapshot_date))
            .limit(1),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None
