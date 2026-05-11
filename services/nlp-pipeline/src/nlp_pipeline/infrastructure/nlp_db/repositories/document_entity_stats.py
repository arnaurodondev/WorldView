"""Document entity stats repository for nlp_db."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from nlp_pipeline.infrastructure.nlp_db.models import DocumentEntityStatsModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import DocumentEntityStats


class DocumentEntityStatsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, stats: DocumentEntityStats) -> None:
        """Insert or update document entity stats (upsert on doc_id PK)."""
        stmt = (
            insert(DocumentEntityStatsModel)
            .values(
                doc_id=stats.doc_id,
                distinct_mention_count=stats.distinct_mention_count,
                high_conf_mention_count=stats.high_conf_mention_count,
                type_distribution=stats.type_distribution,
                updated_at=datetime.now(tz=UTC),
            )
            .on_conflict_do_update(
                index_elements=["doc_id"],
                set_={
                    "distinct_mention_count": stats.distinct_mention_count,
                    "high_conf_mention_count": stats.high_conf_mention_count,
                    "type_distribution": stats.type_distribution,
                    "updated_at": datetime.now(tz=UTC),
                },
            )
        )
        await self._session.execute(stmt)

    async def get(self, doc_id: UUID) -> DocumentEntityStatsModel | None:
        result = await self._session.execute(
            select(DocumentEntityStatsModel).where(DocumentEntityStatsModel.doc_id == doc_id),
        )
        return result.scalar_one_or_none()  # type: ignore[no-any-return]
