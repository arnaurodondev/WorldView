"""SQLAlchemy implementation of ``NPSScoreRepo``."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from portfolio.application.ports.feedback import NPSScoreRecord, NPSScoreRepo
from portfolio.domain.errors import NPSRateLimitError
from portfolio.infrastructure.db.models.nps_score import NPSScoreModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyNPSScoreRepo(NPSScoreRepo):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: NPSScoreRecord) -> None:
        row = NPSScoreModel(
            id=record.id,
            tenant_id=record.tenant_id,
            user_id=record.user_id,
            score=record.score,
            comment=record.comment,
            surface=record.surface,
            created_at=record.created_at,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Belt-and-suspenders: rate limit is enforced primarily in
            # SubmitNPSScoreUseCase (SELECT-then-INSERT). This branch covers
            # the tiny race window where two requests slip past the SELECT
            # under READ COMMITTED. Currently no DB-level unique constraint
            # exists (now() is not IMMUTABLE → cannot live in an index
            # predicate), so this is mostly defensive.
            raise NPSRateLimitError(
                f"User {record.user_id} already submitted an NPS score in the last 30 days",
            ) from exc

    async def find_recent_by_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        since: datetime,
    ) -> NPSScoreRecord | None:
        # Backed by the composite index ix_nps_scores_user_recent
        # (tenant_id, user_id, created_at DESC) — limit 1 for an
        # index-only lookup.
        result = await self._session.execute(
            select(NPSScoreModel)
            .where(
                NPSScoreModel.tenant_id == tenant_id,
                NPSScoreModel.user_id == user_id,
                NPSScoreModel.created_at >= since,
            )
            .order_by(NPSScoreModel.created_at.desc())
            .limit(1),
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return NPSScoreRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            score=row.score,
            comment=row.comment,
            surface=row.surface,
            created_at=row.created_at,
        )

    async def aggregate(
        self,
        tenant_id: UUID,
        *,
        days: int = 30,
    ) -> tuple[int, int, int]:
        from sqlalchemy import case

        from common.time import utc_now  # type: ignore[import-untyped]

        cutoff = utc_now() - timedelta(days=days)
        # WHY CASE WHEN: sums 1 for matching rows, 0 otherwise, in a single
        # SELECT — cheaper than three separate queries with WHERE.
        # NPS bucket definitions: promoters=9-10, passives=7-8, detractors=0-6.
        promoter_sum = func.coalesce(
            func.sum(case((NPSScoreModel.score >= 9, 1), else_=0)),
            0,
        )
        passive_sum = func.coalesce(
            func.sum(case((NPSScoreModel.score.between(7, 8), 1), else_=0)),
            0,
        )
        detractor_sum = func.coalesce(
            func.sum(case((NPSScoreModel.score <= 6, 1), else_=0)),
            0,
        )
        result = await self._session.execute(
            select(promoter_sum, passive_sum, detractor_sum).where(
                NPSScoreModel.tenant_id == tenant_id,
                NPSScoreModel.created_at >= cutoff,
            ),
        )
        row = result.one()
        return int(row[0]), int(row[1]), int(row[2])
