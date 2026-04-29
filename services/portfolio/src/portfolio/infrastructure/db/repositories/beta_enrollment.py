"""SQLAlchemy implementation of ``BetaEnrollmentRepo``."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from portfolio.application.ports.feedback import BetaEnrollmentRecord, BetaEnrollmentRepo
from portfolio.infrastructure.db.models.beta_enrollment import BetaEnrollmentModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyBetaEnrollmentRepo(BetaEnrollmentRepo):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_record(row: BetaEnrollmentModel) -> BetaEnrollmentRecord:
        return BetaEnrollmentRecord(
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            enrolled=row.enrolled,
            programs=list(row.programs) if row.programs else [],
            enrolled_at=row.enrolled_at,
            updated_at=row.updated_at,
        )

    async def get(self, tenant_id: UUID, user_id: UUID) -> BetaEnrollmentRecord | None:
        result = await self._session.execute(
            select(BetaEnrollmentModel).where(
                BetaEnrollmentModel.tenant_id == tenant_id,
                BetaEnrollmentModel.user_id == user_id,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_record(row) if row else None

    async def upsert(self, record: BetaEnrollmentRecord) -> BetaEnrollmentRecord:
        # Composite PK (tenant_id, user_id) — one row per user. We do the
        # SELECT/UPDATE/INSERT dance manually rather than using Postgres's
        # ON CONFLICT clause to keep the repository portable across
        # SQLAlchemy dialects (the rest of the portfolio service does the same).
        from common.time import utc_now  # type: ignore[import-untyped]

        existing = await self._session.execute(
            select(BetaEnrollmentModel).where(
                BetaEnrollmentModel.tenant_id == record.tenant_id,
                BetaEnrollmentModel.user_id == record.user_id,
            ),
        )
        row = existing.scalar_one_or_none()
        now = utc_now()
        if row is None:
            row = BetaEnrollmentModel(
                tenant_id=record.tenant_id,
                user_id=record.user_id,
                enrolled=record.enrolled,
                programs=record.programs,
                enrolled_at=record.enrolled_at or now,
                updated_at=now,
            )
            self._session.add(row)
        else:
            row.enrolled = record.enrolled
            row.programs = record.programs
            row.updated_at = now
        await self._session.flush()
        return self._to_record(row)
