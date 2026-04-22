"""ArticleImpactWindowRepository — SQLAlchemy implementation (PRD-0026 §6.5)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nlp_pipeline.application.ports.repositories import ArticleImpactWindowRepositoryPort
from nlp_pipeline.infrastructure.nlp_db.models import ArticleImpactWindowModel

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import ArticleImpactWindow


class ArticleImpactWindowRepository(ArticleImpactWindowRepositoryPort):
    """SQLAlchemy-backed implementation of :class:`ArticleImpactWindowRepositoryPort`.

    Caller (UoW or worker) is responsible for ``commit()``.
    This class only calls ``execute()`` -- never ``commit()``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_batch(self, windows: list[ArticleImpactWindow]) -> None:
        """Bulk INSERT ON CONFLICT (article_id, entity_id, window_type) DO NOTHING.

        Idempotent (R9): duplicate (article_id, entity_id, window_type) triples are
        silently ignored thanks to idx_article_impact_windows_unique (migration 0009).
        """
        if not windows:
            return

        values = [
            {
                "id": w.id,
                "article_id": w.article_id,
                "entity_id": w.entity_id,
                "symbol": w.symbol,
                "published_at": w.published_at,
                "window_type": str(w.window_type),
                "window_start": w.window_start,
                "window_end": w.window_end,
                "price_start": w.price_start,
                "price_end": w.price_end,
                "delta_pct": w.delta_pct,
                "high_pct": w.high_pct,
                "low_pct": w.low_pct,
                "volume": w.volume,
                "impact_score": w.impact_score,
                "normalisation_cap_pct": w.normalisation_cap_pct,
                "data_quality": str(w.data_quality),
                # computed_at gets server_default (now()) when not supplied
            }
            for w in windows
        ]

        stmt = (
            pg_insert(ArticleImpactWindowModel)
            .values(values)
            .on_conflict_do_nothing(index_elements=["article_id", "entity_id", "window_type"])
        )
        await self._session.execute(stmt)

    async def get_articles_needing_windows(
        self,
        min_age_hours: int,
        batch_size: int,
    ) -> list[tuple[UUID, UUID, str, datetime]]:
        """Return (doc_id, entity_id, symbol, published_at) for article/entity pairs
        that are missing at least one of their expected daily windows.

        Logic (PRD-0026 §6.7 Flow A Phase 1):
          - Article must be old enough (published_at < now() - min_age_hours)
          - Must have a resolved financial_instrument mention
          - Must be missing at least one day_t0 row in article_impact_windows
            (day_t0 is required for ALL labelled articles; t1/t2/t5 are added later)
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

    async def get_max_impact_for_doc(self, doc_id: UUID) -> Decimal:
        """Return max ``impact_score`` across all windows and entities for ``doc_id``.

        Returns ``Decimal("0.0")`` when no windows exist yet.
        Used by Block 5 (signal scoring) inside the article consumer.
        """
        result = await self._session.execute(
            sa.select(func.max(ArticleImpactWindowModel.impact_score)).where(
                ArticleImpactWindowModel.article_id == doc_id
            )
        )
        val = result.scalar_one_or_none()
        return Decimal(str(val)) if val is not None else Decimal("0.0")
