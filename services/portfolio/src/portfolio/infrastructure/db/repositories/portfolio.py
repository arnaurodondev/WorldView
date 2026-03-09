"""SQLAlchemy implementation of PortfolioRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from portfolio.application.ports.repositories import PortfolioRepository
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.enums import PortfolioStatus
from portfolio.infrastructure.db.models.portfolio import PortfolioModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyPortfolioRepository(PortfolioRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: PortfolioModel) -> Portfolio:
        return Portfolio(
            id=row.id,
            tenant_id=row.tenant_id,
            owner_id=row.owner_id,
            name=row.name,
            currency=row.currency,
            status=PortfolioStatus(row.status),
            created_at=row.created_at,
        )

    async def get(self, portfolio_id: UUID, tenant_id: UUID) -> Portfolio | None:
        result = await self._session.execute(
            select(PortfolioModel).where(
                PortfolioModel.id == portfolio_id,
                PortfolioModel.tenant_id == tenant_id,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_by_owner(self, owner_id: UUID, tenant_id: UUID) -> list[Portfolio]:
        result = await self._session.execute(
            select(PortfolioModel).where(
                PortfolioModel.owner_id == owner_id,
                PortfolioModel.tenant_id == tenant_id,
            )
        )
        return [self._to_entity(r) for r in result.scalars()]

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
                created_at=portfolio.created_at,
            )
            self._session.add(row)
        else:
            row.name = portfolio.name
            row.status = str(portfolio.status)
