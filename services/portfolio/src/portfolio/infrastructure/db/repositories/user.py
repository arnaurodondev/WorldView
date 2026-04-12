"""SQLAlchemy implementation of UserRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, update

from portfolio.application.ports.repositories import UserRepository
from portfolio.domain.entities.user import User
from portfolio.domain.enums import TenantUserRole, UserStatus
from portfolio.infrastructure.db.models.user import UserModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: UserModel) -> User:
        return User(
            id=row.id,
            tenant_id=row.tenant_id,
            email=row.email,
            status=UserStatus(row.status),
            created_at=row.created_at,
            external_id=row.external_id,
            role=TenantUserRole(row.role),
        )

    async def get(self, user_id: UUID, tenant_id: UUID) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == user_id, UserModel.tenant_id == tenant_id),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def get_by_email(self, email: str, tenant_id: UUID) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == email, UserModel.tenant_id == tenant_id),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def save(self, user: User) -> None:
        row = await self._session.get(UserModel, user.id)
        if row is None:
            row = UserModel(
                id=user.id,
                tenant_id=user.tenant_id,
                email=user.email,
                status=str(user.status),
                created_at=user.created_at,
                external_id=user.external_id,
                role=str(user.role),
            )
            self._session.add(row)
        else:
            row.email = user.email
            row.status = str(user.status)
            row.external_id = user.external_id
            row.role = str(user.role)

    async def find_by_external_id(self, external_id: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.external_id == external_id),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def find_by_email_without_external_id(self, email: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(
                UserModel.email == email,
                UserModel.external_id.is_(None),  # type: ignore[union-attr]
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def link_external_id(self, user_id: UUID, external_id: str) -> None:
        await self._session.execute(
            update(UserModel).where(UserModel.id == user_id).values(external_id=external_id),
        )

    async def find_by_email_with_conflicting_external_id(self, email: str, current_sub: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(
                UserModel.email == email,
                UserModel.external_id.isnot(None),  # type: ignore[union-attr]
                UserModel.external_id != current_sub,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None
