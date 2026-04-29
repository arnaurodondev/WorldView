"""SQLAlchemy implementation of ``NPSScoreRepo``."""

from __future__ import annotations

from datetime import timedelta
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
            # Partial unique index uq_nps_scores_tenant_user_30d — one score
            # per (tenant, user) per 30 days. Map to a domain-level rate-limit
            # error so the API can return 409.
            if "uq_nps_scores_tenant_user_30d" in str(exc.orig):
                raise NPSRateLimitError(
                    f"User {record.user_id} already submitted an NPS score in the last 30 days"
                ) from exc
            raise

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
