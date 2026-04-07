"""SQLAlchemy adapter for EmailPreference persistence."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alert.application.ports.repositories import EmailPreferenceRepositoryPort
from alert.domain.entities import EmailPreference
from alert.infrastructure.db.models import EmailPreferenceModel
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class EmailPreferenceRepository(EmailPreferenceRepositoryPort):
    """Manages ``email_preferences`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user(self, user_id: UUID, tenant_id: UUID) -> EmailPreference | None:
        """Fetch preferences for a user, or None if no row exists."""
        stmt = select(EmailPreferenceModel).where(
            EmailPreferenceModel.user_id == user_id,
            EmailPreferenceModel.tenant_id == tenant_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(row) if row is not None else None

    async def upsert(self, pref: EmailPreference) -> None:
        """Insert or update an email preferences row (upsert on PK)."""
        stmt = (
            pg_insert(EmailPreferenceModel)
            .values(
                user_id=pref.user_id,
                tenant_id=pref.tenant_id,
                weekly_digest_enabled=pref.weekly_digest_enabled,
                send_day_of_week=pref.send_day_of_week,
                send_hour_utc=pref.send_hour_utc,
                email_address=pref.email_address,
                last_digest_sent_at=pref.last_digest_sent_at,
                created_at=pref.created_at,
                updated_at=utc_now(),
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "weekly_digest_enabled": pref.weekly_digest_enabled,
                    "send_day_of_week": pref.send_day_of_week,
                    "send_hour_utc": pref.send_hour_utc,
                    "email_address": pref.email_address,
                    "last_digest_sent_at": pref.last_digest_sent_at,
                    "updated_at": utc_now(),
                },
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def commit(self) -> None:
        """Commit the current session transaction (N-04: commit inside UoW, not in routes)."""
        await self._session.commit()

    async def list_scheduled_users(self, day: int, hour: int) -> list[EmailPreference]:
        """Return users whose digest is scheduled for *day*/*hour* and not yet sent.

        C-03: Excludes users whose ``last_digest_sent_at`` is within the last
        23 hours — prevents duplicate sends if the scheduler fires slightly
        early or the job is retried within the same run window.
        """
        cutoff = utc_now() - timedelta(hours=23)
        stmt = select(EmailPreferenceModel).where(
            EmailPreferenceModel.weekly_digest_enabled.is_(True),
            EmailPreferenceModel.send_day_of_week == day,
            EmailPreferenceModel.send_hour_utc == hour,
            or_(
                EmailPreferenceModel.last_digest_sent_at.is_(None),
                EmailPreferenceModel.last_digest_sent_at < cutoff,
            ),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_entity(r) for r in rows]

    @staticmethod
    def _to_entity(row: EmailPreferenceModel) -> EmailPreference:
        return EmailPreference(
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            weekly_digest_enabled=row.weekly_digest_enabled,
            send_day_of_week=row.send_day_of_week,
            send_hour_utc=row.send_hour_utc,
            email_address=row.email_address,
            last_digest_sent_at=row.last_digest_sent_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
