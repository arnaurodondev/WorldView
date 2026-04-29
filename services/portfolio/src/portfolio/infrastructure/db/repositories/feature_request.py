"""SQLAlchemy implementation of ``FeatureRequestRepo``."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select, text

from common.time import utc_now  # type: ignore[import-untyped]
from portfolio.application.ports.feedback import FeatureRequestRecord, FeatureRequestRepo
from portfolio.infrastructure.db.models.feature_request import FeatureRequestModel

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
        row.updated_at = utc_now()
        await self._session.flush()
        return self._to_record(row)

    async def refresh_vote_count(self, feature_request_id: UUID) -> int:
        # F-Q1-06: atomic single-statement update — the SELECT and UPDATE
        # run in one statement so concurrent voters cannot lose updates
        # under READ COMMITTED. The previous implementation read count() into
        # Python, then UPDATEd the row — two concurrent transactions both saw
        # count=N and both wrote N, dropping a vote silently.
        stmt = text(
            """
            UPDATE feature_requests
            SET vote_count = (
                SELECT COUNT(*) FROM feature_votes
                WHERE feature_request_id = :id
            ),
            updated_at = now()
            WHERE id = :id
            RETURNING vote_count
            """,
        )
        result = await self._session.execute(stmt, {"id": str(feature_request_id)})
        row = result.first()
        # The row is guaranteed to exist by the caller (UpsertFeatureVoteUseCase
        # checks tenant ownership before invoking refresh) but we defend
        # against None to satisfy mypy and against a hypothetical race where
        # the feature was deleted concurrently.
        return int(row[0]) if row else 0
