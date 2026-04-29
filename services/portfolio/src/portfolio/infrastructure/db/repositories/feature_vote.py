"""SQLAlchemy implementation of ``FeatureVoteRepo``."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from portfolio.application.ports.feedback import FeatureVoteRecord, FeatureVoteRepo
from portfolio.infrastructure.db.models.feature_vote import FeatureVoteModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyFeatureVoteRepo(FeatureVoteRepo):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, record: FeatureVoteRecord) -> bool:
        # Composite PK (feature_request_id, user_id) makes "one vote per user
        # per request" a DB-level invariant. We attempt the insert and rely on
        # IntegrityError to detect the duplicate — the alternative is a
        # SELECT-then-INSERT race window. SAVEPOINT lets the outer transaction
        # continue after a duplicate.
        async with self._session.begin_nested():
            row = FeatureVoteModel(
                feature_request_id=record.feature_request_id,
                user_id=record.user_id,
                tenant_id=record.tenant_id,
                created_at=record.created_at,
            )
            self._session.add(row)
            try:
                await self._session.flush()
                return True
            except IntegrityError:
                # PK violation — vote already exists. Treat as idempotent success.
                return False

    async def has_voted(self, feature_request_id: UUID, user_id: UUID) -> bool:
        result = await self._session.execute(
            select(FeatureVoteModel).where(
                FeatureVoteModel.feature_request_id == feature_request_id,
                FeatureVoteModel.user_id == user_id,
            ),
        )
        return result.scalar_one_or_none() is not None
