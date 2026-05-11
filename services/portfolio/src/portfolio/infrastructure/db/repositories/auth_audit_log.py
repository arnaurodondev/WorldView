"""SQLAlchemy implementation of AuthAuditLogRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from portfolio.application.ports.repositories import AuthAuditLogRepository
from portfolio.infrastructure.db.models.auth_audit_log import AuthAuditLogModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from portfolio.domain.value_objects import AuthAuditEvent


class SqlAlchemyAuthAuditLogRepository(AuthAuditLogRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, event: AuthAuditEvent, user_id: UUID | None) -> None:
        from common.ids import new_uuid  # type: ignore[import-untyped]
        from common.time import utc_now  # type: ignore[import-untyped]

        row = AuthAuditLogModel(
            id=new_uuid(),
            user_id=user_id,
            event_type=str(event.event_type),
            sub=event.sub,
            email=event.email,
            ip_address=event.ip_address,
            detail=dict(event.detail) if event.detail else None,
            created_at=utc_now(),
        )
        self._session.add(row)
