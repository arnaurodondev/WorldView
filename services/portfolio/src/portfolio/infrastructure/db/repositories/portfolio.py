"""SQLAlchemy implementation of PortfolioRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from portfolio.application.ports.repositories import PortfolioRepository
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.enums import PortfolioKind, PortfolioStatus
from portfolio.domain.errors import PortfolioAlreadyExistsError
from portfolio.infrastructure.db.models.portfolio import PortfolioModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyPortfolioRepository(PortfolioRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: PortfolioModel) -> Portfolio:
        # PLAN-0046 Wave 3 / T-46-3-01: ``kind`` is now persisted on the row.
        # Historical rows backfilled by migration 0011 carry ``kind='manual'``.
        return Portfolio(
            id=row.id,
            tenant_id=row.tenant_id,
            owner_id=row.owner_id,
            name=row.name,
            currency=row.currency,
            status=PortfolioStatus(row.status),
            kind=PortfolioKind(row.kind),
            created_at=row.created_at,
        )

    async def find_root_by_owner(self, owner_id: UUID, tenant_id: UUID) -> Portfolio | None:
        """Return the user's ROOT portfolio if one exists, else None.

        PLAN-0046 Wave 3 / T-46-3-02. Used by ``EnsureRootPortfolioUseCase``
        to keep provisioning idempotent. The DB partial unique index
        ``uq_portfolios_owner_root`` guarantees at most one row matches.
        """
        result = await self._session.execute(
            select(PortfolioModel).where(
                PortfolioModel.owner_id == owner_id,
                PortfolioModel.tenant_id == tenant_id,
                PortfolioModel.kind == str(PortfolioKind.ROOT),
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_non_root_active_ids_by_owner(self, owner_id: UUID, tenant_id: UUID) -> list[UUID]:
        """Return ids of all the owner's non-root, active portfolios.

        PLAN-0046 Wave 3 / T-46-3-03. Used by holdings/transactions fan-out
        when the caller targets a ROOT portfolio: we expand the single
        ``portfolio_id`` predicate into ``portfolio_id IN (...sub-portfolios)``.
        """
        result = await self._session.execute(
            select(PortfolioModel.id).where(
                PortfolioModel.owner_id == owner_id,
                PortfolioModel.tenant_id == tenant_id,
                PortfolioModel.kind != str(PortfolioKind.ROOT),
                PortfolioModel.status == str(PortfolioStatus.ACTIVE),
            ),
        )
        return [row for (row,) in result.all()]

    async def get(self, portfolio_id: UUID, tenant_id: UUID) -> Portfolio | None:
        result = await self._session.execute(
            select(PortfolioModel).where(
                PortfolioModel.id == portfolio_id,
                PortfolioModel.tenant_id == tenant_id,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_by_owner(
        self,
        owner_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Portfolio], int]:
        base_where = (
            PortfolioModel.owner_id == owner_id,
            PortfolioModel.tenant_id == tenant_id,
        )
        count_result = await self._session.execute(select(func.count()).select_from(PortfolioModel).where(*base_where))
        total: int = count_result.scalar_one()
        result = await self._session.execute(select(PortfolioModel).where(*base_where).limit(limit).offset(offset))
        return [self._to_entity(r) for r in result.scalars()], total

    async def save(self, portfolio: Portfolio) -> None:
        row = await self._session.get(PortfolioModel, portfolio.id)
        if row is None:
            row = PortfolioModel(
                id=portfolio.id,
                tenant_id=portfolio.tenant_id,
                owner_id=portfolio.owner_id,
                name=portfolio.name,
                currency=portfolio.currency,
                status=str(portfolio.status),
                # PLAN-0046 Wave 3 / T-46-3-01: persist the discriminator on
                # initial insert. Subsequent updates do not mutate ``kind``.
                kind=str(portfolio.kind),
                created_at=portfolio.created_at,
            )
            self._session.add(row)
            try:
                await self._session.flush()
            except IntegrityError as exc:
                raise PortfolioAlreadyExistsError(
                    f"Portfolio with name '{portfolio.name}' already exists for owner {portfolio.owner_id}",
                ) from exc
        else:
            row.name = portfolio.name
            row.status = str(portfolio.status)
