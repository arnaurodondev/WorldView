"""Alert repository — CRUD for the ``alerts`` table."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from alert.domain.entities import Alert
from alert.domain.enums import AlertSeverity, AlertType
from alert.domain.errors import DuplicateAlertError
from alert.infrastructure.db.models import AlertModel
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
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
            tenant_id=alert.tenant_id,
            created_at=alert.created_at,
            title=alert.title,
            ticker=alert.ticker,
            entity_name=alert.entity_name,
            signal_label=alert.signal_label,
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

    async def acknowledge(
        self,
        alert_id: UUID,
        user_id: UUID,
        ack_time: datetime | None = None,
    ) -> bool:
        """Mark an alert acknowledged.

        Idempotent: if ``acknowledged_at`` is already set, returns False (no
        update applied) so the use case can preserve the original ack metadata.

        Returns True iff a row was updated.
        """
        stmt = (
            update(AlertModel)
            .where(
                AlertModel.alert_id == alert_id,
                AlertModel.acknowledged_at.is_(None),
            )
            .values(
                acknowledged_at=ack_time or utc_now(),
                acknowledged_by_user_id=user_id,
            )
        )
        result = await self._session.execute(stmt)
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined,no-any-return]

    async def snooze(self, alert_id: UUID, snooze_until: datetime) -> bool:
        """Set ``snooze_until`` on an alert. Returns True iff a row was updated."""
        stmt = update(AlertModel).where(AlertModel.alert_id == alert_id).values(snooze_until=snooze_until)
        result = await self._session.execute(stmt)
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined,no-any-return]

    async def list_history(
        self,
        tenant_id: UUID,
        *,
        status: str = "all",
        severity: AlertSeverity | None = None,
        entity_id: UUID | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Alert]:
        """List alerts in a tenant's history with the given filters.

        ``status`` is one of:
          - ``active``: ``acknowledged_at IS NULL AND
            (snooze_until IS NULL OR snooze_until < NOW())``
          - ``acknowledged``: ``acknowledged_at IS NOT NULL``
          - ``snoozed``: ``snooze_until IS NOT NULL AND snooze_until >= NOW() AND
            acknowledged_at IS NULL``
          - ``all``: no status filter (default).

        Tenant-scoped: only returns rows where ``tenant_id`` matches.
        """
        now = utc_now()
        stmt = select(AlertModel).where(AlertModel.tenant_id == tenant_id)

        if status == "active":
            stmt = stmt.where(
                AlertModel.acknowledged_at.is_(None),
                or_(
                    AlertModel.snooze_until.is_(None),
                    AlertModel.snooze_until < now,
                ),
            )
        elif status == "acknowledged":
            stmt = stmt.where(AlertModel.acknowledged_at.is_not(None))
        elif status == "snoozed":
            stmt = stmt.where(
                AlertModel.acknowledged_at.is_(None),
                AlertModel.snooze_until.is_not(None),
                AlertModel.snooze_until >= now,
            )
        # else "all" — no extra filter

        if severity is not None:
            stmt = stmt.where(AlertModel.severity == str(severity))
        if entity_id is not None:
            stmt = stmt.where(AlertModel.entity_id == entity_id)
        if from_dt is not None:
            stmt = stmt.where(AlertModel.created_at >= from_dt)
        if to_dt is not None:
            stmt = stmt.where(AlertModel.created_at <= to_dt)

        stmt = stmt.order_by(AlertModel.created_at.desc()).limit(limit).offset(offset)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_entity(r) for r in rows]

    async def count_history(
        self,
        tenant_id: UUID,
        *,
        status: str = "all",
        severity: AlertSeverity | None = None,
        entity_id: UUID | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> int:
        """Return the universe count for a tenant's filtered history.

        Mirrors the WHERE composition of ``list_history`` exactly (sans
        LIMIT/OFFSET) so pagination math (universe = count_history) lines up
        with the rows returned by the next page's list_history call.
        QA-iter1 C-3: the route used to derive ``has_more`` from the page row
        count, which never set the flag for "fits-in-one-page" universes —
        the new ``total`` is the canonical filtered universe.
        """
        now = utc_now()
        stmt = select(func.count(AlertModel.alert_id)).where(AlertModel.tenant_id == tenant_id)

        if status == "active":
            stmt = stmt.where(
                AlertModel.acknowledged_at.is_(None),
                or_(
                    AlertModel.snooze_until.is_(None),
                    AlertModel.snooze_until < now,
                ),
            )
        elif status == "acknowledged":
            stmt = stmt.where(AlertModel.acknowledged_at.is_not(None))
        elif status == "snoozed":
            stmt = stmt.where(
                AlertModel.acknowledged_at.is_(None),
                AlertModel.snooze_until.is_not(None),
                AlertModel.snooze_until >= now,
            )
        # else "all" — no extra filter

        if severity is not None:
            stmt = stmt.where(AlertModel.severity == str(severity))
        if entity_id is not None:
            stmt = stmt.where(AlertModel.entity_id == entity_id)
        if from_dt is not None:
            stmt = stmt.where(AlertModel.created_at >= from_dt)
        if to_dt is not None:
            stmt = stmt.where(AlertModel.created_at <= to_dt)

        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

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
            tenant_id=row.tenant_id,
            title=row.title,
            ticker=row.ticker,
            entity_name=row.entity_name,
            signal_label=row.signal_label,
            acknowledged_at=row.acknowledged_at,
            acknowledged_by_user_id=row.acknowledged_by_user_id,
            snooze_until=row.snooze_until,
        )
