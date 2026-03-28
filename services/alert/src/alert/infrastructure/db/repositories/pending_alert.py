"""PendingAlert repository — manages ``pending_alerts`` rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, update

from alert.domain.entities import PendingAlert
from alert.infrastructure.db.models import PendingAlertModel
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class PendingAlertRepository:
    """Manages ``pending_alerts`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, pending: PendingAlert) -> None:
        """Insert a new pending alert row."""
        row = PendingAlertModel(
            pending_id=pending.pending_id,
            user_id=pending.user_id,
            alert_id=pending.alert_id,
            created_at=pending.created_at,
            delivered_at=pending.delivered_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def list_by_user(self, user_id: UUID, limit: int = 50, offset: int = 0) -> list[PendingAlert]:
        """List undelivered pending alerts for a user, newest first."""
        stmt = (
            select(PendingAlertModel)
            .where(PendingAlertModel.user_id == user_id, PendingAlertModel.delivered_at.is_(None))
            .order_by(PendingAlertModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_entity(r) for r in rows]

    async def acknowledge(self, user_id: UUID, alert_id: UUID) -> bool:
        """Mark a pending alert as delivered.  Returns ``True`` if a row was updated."""
        stmt = (
            update(PendingAlertModel)
            .where(
                PendingAlertModel.user_id == user_id,
                PendingAlertModel.alert_id == alert_id,
                PendingAlertModel.delivered_at.is_(None),
            )
            .values(delivered_at=utc_now())
        )
        result = await self._session.execute(stmt)
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined,no-any-return]

    @staticmethod
    def _to_entity(row: PendingAlertModel) -> PendingAlert:
        return PendingAlert(
            pending_id=row.pending_id,
            user_id=row.user_id,
            alert_id=row.alert_id,
            created_at=row.created_at,
            delivered_at=row.delivered_at,
        )
