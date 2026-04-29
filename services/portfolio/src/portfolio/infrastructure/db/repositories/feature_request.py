"""SQLAlchemy implementation of ``FeatureRequestRepo``."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select

from portfolio.application.ports.feedback import FeatureRequestRecord, FeatureRequestRepo
from portfolio.infrastructure.db.models.feature_request import FeatureRequestModel
from portfolio.infrastructure.db.models.feature_vote import FeatureVoteModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyFeatureRequestRepo(FeatureRequestRepo):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_record(row: FeatureRequestModel) -> FeatureRequestRecord:
        return FeatureRequestRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            created_by_user_id=row.created_by_user_id,
            title=row.title,
            description=row.description,
            status=row.status,
            category=row.category,
            vote_count=row.vote_count,
            is_public=row.is_public,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def add(self, record: FeatureRequestRecord) -> None:
        row = FeatureRequestModel(
            id=record.id,
            tenant_id=record.tenant_id,
            created_by_user_id=record.created_by_user_id,
            title=record.title,
            description=record.description,
            status=record.status,
            category=record.category,
            vote_count=record.vote_count,
            is_public=record.is_public,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def get(self, feature_request_id: UUID, tenant_id: UUID) -> FeatureRequestRecord | None:
        result = await self._session.execute(
            select(FeatureRequestModel).where(
                FeatureRequestModel.id == feature_request_id,
                FeatureRequestModel.tenant_id == tenant_id,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_record(row) if row else None

    async def list(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        category: str | None = None,
        is_public: bool | None = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[FeatureRequestRecord], int]:
        base = select(FeatureRequestModel).where(FeatureRequestModel.tenant_id == tenant_id)
        count_q = (
            select(func.count()).select_from(FeatureRequestModel).where(FeatureRequestModel.tenant_id == tenant_id)
        )
        if status is not None:
            base = base.where(FeatureRequestModel.status == status)
            count_q = count_q.where(FeatureRequestModel.status == status)
        if category is not None:
            base = base.where(FeatureRequestModel.category == category)
            count_q = count_q.where(FeatureRequestModel.category == category)
        if is_public is not None:
            base = base.where(FeatureRequestModel.is_public == is_public)
            count_q = count_q.where(FeatureRequestModel.is_public == is_public)

        # Roadmap-style ordering: highest votes first, ties broken by recency.
        base = (
            base.order_by(
                FeatureRequestModel.vote_count.desc(),
                FeatureRequestModel.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )

        rows = (await self._session.execute(base)).scalars().all()
        total = (await self._session.execute(count_q)).scalar_one()
        return [self._to_record(r) for r in rows], int(total)

    async def update(
        self,
        feature_request_id: UUID,
        tenant_id: UUID,
        *,
        status: str | None = None,
        category: str | None = None,
        is_public: bool | None = None,
    ) -> FeatureRequestRecord | None:
        row = await self._session.get(FeatureRequestModel, feature_request_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        if status is not None:
            row.status = status
        if category is not None:
            row.category = category
        if is_public is not None:
            row.is_public = is_public
        from common.time import utc_now  # type: ignore[import-untyped]

        row.updated_at = utc_now()
        await self._session.flush()
        return self._to_record(row)

    async def refresh_vote_count(self, feature_request_id: UUID) -> int:
        # Recompute vote_count from feature_votes inside the same transaction
        # so the denorm column never lags reality. Returns the new count so
        # callers can echo it back to the client without a re-fetch.
        count_result = await self._session.execute(
            select(func.count())
            .select_from(FeatureVoteModel)
            .where(
                FeatureVoteModel.feature_request_id == feature_request_id,
            ),
        )
        new_count = int(count_result.scalar_one())
        row = await self._session.get(FeatureRequestModel, feature_request_id)
        if row is not None:
            row.vote_count = new_count
            await self._session.flush()
        return new_count
