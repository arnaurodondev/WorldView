"""ArticlePriceImpactRepository — DEPRECATED (PRD-0026).

The ``article_price_impacts`` table was replaced by ``article_impact_windows``
in migration 0009.  This class is retained for Wave 3 backward compatibility
while ``PriceImpactLabellingWorker`` is being migrated (Wave 4).

DO NOT use this repository in new code.  Use ``ArticleImpactWindowRepository``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import func, text

from nlp_pipeline.application.ports.repositories import PriceImpactRepositoryPort
from nlp_pipeline.infrastructure.nlp_db.models import ArticleImpactWindowModel

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import ArticlePriceImpact


class ArticlePriceImpactRepository(PriceImpactRepositoryPort):
    """DEPRECATED: Use ArticleImpactWindowRepository for new code.

    Retained during Wave 3 while PriceImpactLabellingWorker is being updated.
    get_max_impact_for_doc queries article_impact_windows (the new table);
    upsert/get_by_article_id are no-ops since the old table no longer exists.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, impact: ArticlePriceImpact) -> None:
        """No-op — article_price_impacts table was dropped in migration 0009.

        PriceImpactLabellingWorker will be updated to use ArticleImpactWindowRepository
        in Wave 4 (PRD-0026).
        """

    async def get_by_article_id(self, article_id: UUID) -> ArticlePriceImpact | None:
        """Always returns None — article_price_impacts table no longer exists."""
        return None

    async def get_max_impact_for_doc(self, doc_id: UUID) -> Decimal:
        """Return max impact_score from article_impact_windows for doc_id.

        Queries the new multi-window table; returns Decimal('0.0') when no windows.
        """
        result = await self._session.execute(
            sa.select(func.max(ArticleImpactWindowModel.impact_score)).where(
                ArticleImpactWindowModel.article_id == doc_id
            )
        )
        val = result.scalar_one_or_none()
        return Decimal(str(val)) if val is not None else Decimal("0.0")

    async def get_unlabelled_articles(self, min_age_hours: int, batch_size: int) -> list[tuple[UUID, list[UUID]]]:
        """DEPRECATED — use ArticleImpactWindowRepository.get_articles_needing_windows."""
        return []

    async def get_unlabelled_article_details(
        self, min_age_hours: int, batch_size: int
    ) -> list[tuple[UUID, UUID, str, datetime]]:
        """Return unlabelled article details from article_impact_windows perspective.

        Finds articles where day_t0 window is missing (Wave 4 will replace this with
        ArticleImpactWindowRepository.get_articles_needing_windows).
        """
        stmt = text(
            """
            WITH candidate_docs AS (
                SELECT DISTINCT em.doc_id
                FROM entity_mentions em
                JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id
                WHERE em.resolved_entity_id IS NOT NULL
                  AND em.mention_class = 'financial_instrument'
                  AND dsm.published_at IS NOT NULL
                  AND dsm.published_at < now() - make_interval(hours => :min_age_hours)
                  AND NOT EXISTS (
                      SELECT 1 FROM article_impact_windows aiw
                      WHERE aiw.article_id = em.doc_id
                        AND aiw.entity_id  = em.resolved_entity_id
                        AND aiw.window_type = 'day_t0'
                  )
                LIMIT :batch_size
            )
            SELECT em.doc_id,
                   em.resolved_entity_id AS entity_id,
                   em.mention_text       AS symbol,
                   dsm.published_at
            FROM entity_mentions em
            JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id
            JOIN candidate_docs cd           ON cd.doc_id = em.doc_id
            WHERE em.resolved_entity_id IS NOT NULL
              AND em.mention_class = 'financial_instrument'
              AND dsm.published_at IS NOT NULL
            ORDER BY em.doc_id
            """
        ).bindparams(min_age_hours=min_age_hours, batch_size=batch_size)

        result = await self._session.execute(stmt)
        rows = result.all()
        return [(row.doc_id, row.entity_id, row.symbol, row.published_at) for row in rows]
