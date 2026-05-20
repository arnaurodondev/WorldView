"""SQLAlchemy implementation of NotificationPreferencesRepository.

W1-BACKEND: added to support MED-022 / CRIT-004 notification preferences
endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert

from portfolio.application.ports.repositories import NotificationPreferencesRepository
from portfolio.domain.entities.notification_preferences import NotificationPreferences
from portfolio.infrastructure.db.models.notification_preferences import NotificationPreferencesModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyNotificationPreferencesRepository(NotificationPreferencesRepository):
    """Postgres-backed notification preferences repository.

    Uses PostgreSQL ``INSERT … ON CONFLICT DO UPDATE`` for idempotent upserts.
    The PK conflict target is ``tenant_id`` (the only primary key column).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: NotificationPreferencesModel) -> NotificationPreferences:
        return NotificationPreferences(
            tenant_id=row.tenant_id,
            price_alerts=row.price_alerts,
            news_alerts=row.news_alerts,
            movers_alerts=row.movers_alerts,
            contradiction_alerts=row.contradiction_alerts,
            updated_at=row.updated_at,
        )

    async def get(self, tenant_id: UUID) -> NotificationPreferences | None:
        row = await self._session.get(NotificationPreferencesModel, tenant_id)
        return self._to_entity(row) if row is not None else None

    async def upsert(self, prefs: NotificationPreferences) -> None:
        """INSERT … ON CONFLICT (tenant_id) DO UPDATE — fully idempotent.

        WHY pg_insert (not session.merge): ``session.merge`` performs a
        SELECT + INSERT/UPDATE which is a TOCTOU race for concurrent callers.
        The PostgreSQL-native upsert is atomic in a single statement.
        """
        stmt = (
            pg_insert(NotificationPreferencesModel)
            .values(
                tenant_id=prefs.tenant_id,
                price_alerts=prefs.price_alerts,
                news_alerts=prefs.news_alerts,
                movers_alerts=prefs.movers_alerts,
                contradiction_alerts=prefs.contradiction_alerts,
                updated_at=prefs.updated_at,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id"],
                set_={
                    "price_alerts": prefs.price_alerts,
                    "news_alerts": prefs.news_alerts,
                    "movers_alerts": prefs.movers_alerts,
                    "contradiction_alerts": prefs.contradiction_alerts,
                    "updated_at": prefs.updated_at,
                },
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
