"""Alert repository — CRUD for the ``alerts`` table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from alert.domain.entities import Alert
from alert.domain.enums import AlertSeverity, AlertType
from alert.domain.errors import DuplicateAlertError
from alert.infrastructure.db.models import AlertModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class AlertRepository:
    """Manages ``alerts`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, alert: Alert) -> None:
        """Persist an alert.  Raises ``DuplicateAlertError`` on dedup_key collision."""
        row = AlertModel(
            alert_id=alert.alert_id,
            entity_id=alert.entity_id,
            alert_type=str(alert.alert_type),
            source_event_id=alert.source_event_id,
            source_topic=alert.source_topic,
            payload=alert.payload,
            dedup_key=alert.dedup_key,
            severity=str(alert.severity),
            created_at=alert.created_at,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # DO NOT call self._session.rollback() here — the outer async with session_factory()
            # context manager owns the session lifecycle and handles rollback via __aexit__.
            # Calling rollback here would poison the shared session (BP-141).
            raise DuplicateAlertError(f"Duplicate dedup_key: {alert.dedup_key}") from exc

    async def get_by_id(self, alert_id: UUID) -> Alert | None:
        """Return an alert by its ID, or ``None``."""
        stmt = select(AlertModel).where(AlertModel.alert_id == alert_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return self._to_entity(row)

    async def exists_by_dedup_key(self, dedup_key: str) -> bool:
        """Check whether an alert with the given dedup_key already exists."""
        stmt = select(AlertModel.alert_id).where(AlertModel.dedup_key == dedup_key).limit(1)
        result = (await self._session.execute(stmt)).scalar_one_or_none()
        return result is not None

    @staticmethod
    def _to_entity(row: AlertModel) -> Alert:
        try:
            sev = AlertSeverity(row.severity)
        except ValueError:
            sev = AlertSeverity.LOW  # safe default — forward-compat guard (F-106)
        return Alert(
            alert_id=row.alert_id,
            entity_id=row.entity_id,
            alert_type=AlertType(row.alert_type),
            source_event_id=row.source_event_id,
            source_topic=row.source_topic,
            payload=dict(row.payload),
            dedup_key=row.dedup_key,
            severity=sev,
            created_at=row.created_at,
        )
