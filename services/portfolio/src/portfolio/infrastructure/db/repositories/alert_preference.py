"""SQLAlchemy implementations of AlertPreferenceRepository and EntitySuppressionRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from portfolio.application.ports.repositories import AlertPreferenceRepository, EntitySuppressionRepository
from portfolio.domain.entities.alert_preference import AlertPreference, EntitySuppression
from portfolio.domain.enums import AlertType
from portfolio.infrastructure.db.models.alert_preference import AlertPreferenceModel
from portfolio.infrastructure.db.models.entity_suppression import EntitySuppressionModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyAlertPreferenceRepository(AlertPreferenceRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: AlertPreferenceModel) -> AlertPreference:
        return AlertPreference(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            alert_type=AlertType(row.alert_type),
            enabled=row.enabled,
            updated_at=row.updated_at,
        )

    async def get_by_user(self, user_id: UUID, tenant_id: UUID) -> list[AlertPreference]:
        result = await self._session.execute(
            select(AlertPreferenceModel).where(
                AlertPreferenceModel.user_id == user_id,
                AlertPreferenceModel.tenant_id == tenant_id,
            ),
        )
        return [self._to_entity(r) for r in result.scalars()]

    async def upsert(self, pref: AlertPreference) -> None:
        stmt = (
            pg_insert(AlertPreferenceModel)
            .values(
                id=pref.id,
                tenant_id=pref.tenant_id,
                user_id=pref.user_id,
                alert_type=str(pref.alert_type),
                enabled=pref.enabled,
                updated_at=pref.updated_at,
            )
            .on_conflict_do_update(
                constraint="uq_alert_preferences_user_type",
                set_={
                    "enabled": pref.enabled,
                    "updated_at": pref.updated_at,
                },
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()


class SqlAlchemyEntitySuppressionRepository(EntitySuppressionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: EntitySuppressionModel) -> EntitySuppression:
        return EntitySuppression(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            entity_id=row.entity_id,
            suppressed_at=row.suppressed_at,
        )

    async def list_by_user(self, user_id: UUID, tenant_id: UUID) -> list[EntitySuppression]:
        result = await self._session.execute(
            select(EntitySuppressionModel).where(
                EntitySuppressionModel.user_id == user_id,
                EntitySuppressionModel.tenant_id == tenant_id,
            ),
        )
        return [self._to_entity(r) for r in result.scalars()]

    async def get(self, user_id: UUID, entity_id: UUID) -> EntitySuppression | None:
        result = await self._session.execute(
            select(EntitySuppressionModel).where(
                EntitySuppressionModel.user_id == user_id,
                EntitySuppressionModel.entity_id == entity_id,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def save(self, suppression: EntitySuppression) -> None:
        row = await self._session.get(EntitySuppressionModel, suppression.id)
        if row is None:
            row = EntitySuppressionModel(
                id=suppression.id,
                tenant_id=suppression.tenant_id,
                user_id=suppression.user_id,
                entity_id=suppression.entity_id,
                suppressed_at=suppression.suppressed_at,
            )
            self._session.add(row)
            await self._session.flush()

    async def delete(self, user_id: UUID, entity_id: UUID) -> None:
        result = await self._session.execute(
            select(EntitySuppressionModel).where(
                EntitySuppressionModel.user_id == user_id,
                EntitySuppressionModel.entity_id == entity_id,
            ),
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()
