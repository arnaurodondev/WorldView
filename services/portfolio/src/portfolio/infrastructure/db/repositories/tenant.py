"""SQLAlchemy implementation of TenantRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from portfolio.application.ports.repositories import TenantRepository
from portfolio.domain.entities.tenant import Tenant
from portfolio.domain.enums import TenantStatus
from portfolio.infrastructure.db.models.tenant import TenantModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyTenantRepository(TenantRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: UUID) -> Tenant | None:
        result = await self._session.execute(select(TenantModel).where(TenantModel.id == tenant_id))
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return Tenant(
            id=row.id,
            name=row.name,
            status=TenantStatus(row.status),
            created_at=row.created_at,
        )

    async def save(self, tenant: Tenant) -> None:
        row = await self._session.get(TenantModel, tenant.id)
        if row is None:
            row = TenantModel(
                id=tenant.id,
                name=tenant.name,
                status=str(tenant.status),
                created_at=tenant.created_at,
            )
            self._session.add(row)
        else:
            row.name = tenant.name
            row.status = str(tenant.status)
