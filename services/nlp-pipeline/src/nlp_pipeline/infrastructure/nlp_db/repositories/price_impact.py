"""ArticlePriceImpactRepository — concrete SQLAlchemy implementation (PRD-0020 §6.5)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nlp_pipeline.application.ports.repositories import PriceImpactRepositoryPort
from nlp_pipeline.infrastructure.nlp_db.models import ArticlePriceImpactModel

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import ArticlePriceImpact


def _to_domain(row: ArticlePriceImpactModel) -> ArticlePriceImpact:
    """Convert ORM row → domain entity (preserves existing ``id``)."""
    from nlp_pipeline.domain.models import ArticlePriceImpact

    return ArticlePriceImpact(
        article_id=row.article_id,
        entity_id=row.entity_id,
        symbol=row.symbol,
        published_at=row.published_at,
        ohlcv_date=row.ohlcv_date,
        price_open=row.price_open,
        price_close=row.price_close,
        price_delta_pct=row.price_delta_pct,
        impact_score=row.impact_score,
        next_day_delta_pct=row.next_day_delta_pct,
        max_intraday_range_pct=row.max_intraday_range_pct,
        id=row.id,
    )


class ArticlePriceImpactRepository(PriceImpactRepositoryPort):
    """SQLAlchemy-backed implementation of :class:`PriceImpactRepositoryPort`.

    Caller (UoW) is responsible for ``commit()``; this class only calls
    ``execute()`` / ``flush()`` — never ``commit()``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, impact: ArticlePriceImpact) -> None:
        """INSERT ON CONFLICT (article_id) DO NOTHING — idempotent (R9)."""
        stmt = (
            pg_insert(ArticlePriceImpactModel)
            .values(
                id=impact.id,
                article_id=impact.article_id,
                entity_id=impact.entity_id,
                symbol=impact.symbol,
                published_at=impact.published_at,
                ohlcv_date=impact.ohlcv_date,
                price_open=impact.price_open,
                price_close=impact.price_close,
                price_delta_pct=impact.price_delta_pct,
                next_day_delta_pct=impact.next_day_delta_pct,
                max_intraday_range_pct=impact.max_intraday_range_pct,
                impact_score=impact.impact_score,
            )
            .on_conflict_do_nothing(index_elements=["article_id"])
        )
        await self._session.execute(stmt)

    async def get_by_article_id(self, article_id: UUID) -> ArticlePriceImpact | None:
        result = await self._session.execute(
            sa.select(ArticlePriceImpactModel).where(ArticlePriceImpactModel.article_id == article_id)
        )
        row = result.scalar_one_or_none()
        return _to_domain(row) if row is not None else None

    async def get_max_impact_for_doc(self, doc_id: UUID) -> Decimal:
        """Return max impact_score for all entities linked to ``doc_id``.

        ``article_id`` in the table IS the content-store ``doc_id`` —
        one row per article, not per entity.
        Returns ``Decimal("0.0")`` when no label exists yet.
        """
        result = await self._session.execute(
            sa.select(func.max(ArticlePriceImpactModel.impact_score)).where(
                ArticlePriceImpactModel.article_id == doc_id
            )
        )
        val = result.scalar_one_or_none()
        return Decimal(str(val)) if val is not None else Decimal("0.0")

    async def get_unlabelled_article_details(
        self, min_age_hours: int, batch_size: int
    ) -> list[tuple[UUID, UUID, str, datetime]]:
        """Return ``(doc_id, entity_id, symbol, published_at)`` rows (PRD-0020 §6.5).

        Uses a CTE to limit to ``batch_size`` distinct doc_ids, then joins back to
        get all financial_instrument mentions for those docs in one round-trip.
        """

        stmt = text(
            """
            WITH unlabelled_docs AS (
                SELECT DISTINCT em.doc_id
                FROM entity_mentions em
                JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id
                WHERE em.resolved_entity_id IS NOT NULL
                  AND em.mention_class = 'financial_instrument'
                  AND dsm.published_at IS NOT NULL
                  AND em.doc_id NOT IN (SELECT article_id FROM article_price_impacts)
                  AND dsm.published_at < now() - make_interval(hours => :min_age_hours)
                LIMIT :batch_size
            )
            SELECT em.doc_id,
                   em.resolved_entity_id AS entity_id,
                   em.mention_text       AS symbol,
                   dsm.published_at
            FROM entity_mentions em
            JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id
            JOIN unlabelled_docs ud ON ud.doc_id = em.doc_id
            WHERE em.resolved_entity_id IS NOT NULL
              AND em.mention_class = 'financial_instrument'
              AND dsm.published_at IS NOT NULL
            ORDER BY em.doc_id
            """
        ).bindparams(min_age_hours=min_age_hours, batch_size=batch_size)

        result = await self._session.execute(stmt)
        rows = result.all()
        return [(row.doc_id, row.entity_id, row.symbol, row.published_at) for row in rows]

    async def get_unlabelled_articles(self, min_age_hours: int, batch_size: int) -> list[tuple[UUID, list[UUID]]]:
        """Return unlabelled articles with resolved entities (PRD-0020 §6.5).

        Joins ``entity_mentions`` with ``document_source_metadata`` (for
        ``published_at``), excludes docs already in ``article_price_impacts``,
        and filters to articles older than ``min_age_hours``.
        """
        stmt = text(
            """
            SELECT em.doc_id,
                   array_agg(DISTINCT em.resolved_entity_id) AS entity_ids
            FROM entity_mentions em
            JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id
            WHERE em.resolved_entity_id IS NOT NULL
              AND em.doc_id NOT IN (
                  SELECT article_id FROM article_price_impacts
              )
              AND dsm.published_at < now() - make_interval(hours => :min_age_hours)
            GROUP BY em.doc_id
            LIMIT :batch_size
            """
        ).bindparams(min_age_hours=min_age_hours, batch_size=batch_size)

        result = await self._session.execute(stmt)
        rows = result.all()
        return [(row.doc_id, list(row.entity_ids)) for row in rows]
