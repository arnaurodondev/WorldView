"""SQLAlchemy implementation of NewsQueryPort (PRD-0026 §6.7 Flow C + Flow D).

Two raw-SQL CTEs compute display_relevance_score at query time from:
  - article_impact_windows (multi-window price impact)
  - document_source_metadata (title, url, llm_relevance_score)
  - routing_decisions (composite_score, routing_tier)

BP-069: nullable params (:routing_tier, :min_display_score) use IS NULL checks,
never bare equality with None, to avoid NULL = NULL (always false in SQL).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from nlp_pipeline.application.ports.repositories import NewsQueryPort, RankedArticleData

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Shared SQL fragments
# ---------------------------------------------------------------------------

# CTE that pivots article_impact_windows into 4 named columns + market_impact_score.
_WINDOW_PIVOT_FRAGMENT = """\
    SELECT article_id,
           MAX(CASE WHEN window_type = 'day_t0' THEN impact_score ELSE NULL END) AS day_t0_score,
           MAX(CASE WHEN window_type = 'day_t1' THEN impact_score ELSE NULL END) AS day_t1_score,
           MAX(CASE WHEN window_type = 'day_t2' THEN impact_score ELSE NULL END) AS day_t2_score,
           MAX(CASE WHEN window_type = 'day_t5' THEN impact_score ELSE NULL END) AS day_t5_score,
           GREATEST(
               MAX(CASE WHEN window_type = 'day_t0' THEN impact_score ELSE NULL END),
               MAX(CASE WHEN window_type = 'day_t1' THEN impact_score ELSE NULL END)
           ) AS market_impact_score
    FROM article_impact_windows
"""

# CASE expression computing display_relevance_score (PRD-0026 §6.5).
#   full-signal: 0.50 * market + 0.40 * llm + 0.10 * routing
#   market-only: 0.70 * market + 0.30 * routing
#   llm-only:    0.60 * llm + 0.40 * routing
#   routing-only: 0.40 * routing
_DISPLAY_SCORE_CASE = """\
           CASE
               WHEN {market} > 0 AND {llm} IS NOT NULL
                   THEN 0.50 * {market} + 0.40 * {llm}
                        + 0.10 * COALESCE({routing}, 0.0)
               WHEN {market} > 0
                   THEN 0.70 * {market}
                        + 0.30 * COALESCE({routing}, 0.0)
               WHEN {llm} IS NOT NULL
                   THEN 0.60 * {llm}
                        + 0.40 * COALESCE({routing}, 0.0)
               ELSE COALESCE({routing}, 0.0) * 0.40
           END"""

# ---------------------------------------------------------------------------
# Flow C — global top news (PRD-0026 §6.7 Flow C)
# ---------------------------------------------------------------------------

_TOP_NEWS_SQL = (
    "WITH article_market_impact AS (\n" + _WINDOW_PIVOT_FRAGMENT + "    GROUP BY article_id\n"
    """),
article_primary_entity AS (
    SELECT DISTINCT ON (article_id)
           article_id,
           entity_id AS primary_entity_id,
           symbol    AS primary_entity_symbol
    FROM article_impact_windows
    WHERE window_type = 'day_t0'
    ORDER BY article_id, impact_score DESC NULLS LAST
),
counts AS (
    SELECT dsm.doc_id,
           dsm.title,
           dsm.url,
           dsm.published_at,
           dsm.source_type,
           dsm.source_name,
           dsm.llm_relevance_score,
           dsm.sentiment,
           dsm.impact_score,
           rd.composite_score                                AS routing_score,
           COALESCE(rd.final_routing_tier, rd.routing_tier) AS routing_tier,
           ami.day_t0_score,
           ami.day_t1_score,
           ami.day_t2_score,
           ami.day_t5_score,
           ami.market_impact_score,
"""
    + _DISPLAY_SCORE_CASE.format(
        market="ami.market_impact_score",
        llm="dsm.llm_relevance_score",
        routing="rd.composite_score",
    )
    + """                                                          AS display_relevance_score,
           COUNT(*) OVER()                                    AS total_count
    FROM document_source_metadata dsm
    LEFT JOIN article_market_impact ami ON ami.article_id = dsm.doc_id
    LEFT JOIN routing_decisions rd      ON rd.doc_id      = dsm.doc_id
    WHERE dsm.published_at >= now() - :hours * interval '1 hour'
      AND (
          CAST(:routing_tier AS TEXT) IS NULL
          OR COALESCE(rd.final_routing_tier, rd.routing_tier) = CAST(:routing_tier AS TEXT)
      )
)
SELECT c.*,
       ape.primary_entity_id,
       ape.primary_entity_symbol
FROM counts c
LEFT JOIN article_primary_entity ape ON ape.article_id = c.doc_id
WHERE (
    CAST(:min_display_score AS DOUBLE PRECISION) IS NULL
    OR c.display_relevance_score >= CAST(:min_display_score AS DOUBLE PRECISION)
)
ORDER BY display_relevance_score DESC, published_at DESC
LIMIT :limit OFFSET :offset
"""
)

# ---------------------------------------------------------------------------
# Flow D — entity articles (PRD-0026 §6.7 Flow D)
# ---------------------------------------------------------------------------

_ENTITY_ARTICLES_SQL = (
    "WITH entity_article_ids AS (\n"
    "    SELECT DISTINCT em.doc_id AS article_id\n"
    "    FROM entity_mentions em\n"
    "    WHERE em.resolved_entity_id = :entity_id\n"
    "      AND (em.tenant_id IS NULL OR em.tenant_id = CAST(:tenant_id AS UUID))\n"
    "),\n"
    "article_windows AS (\n"
    + _WINDOW_PIVOT_FRAGMENT
    + "    WHERE article_id IN (SELECT article_id FROM entity_article_ids)\n"
    "    GROUP BY article_id\n"
    # ranked CTE materialises display_relevance_score so ORDER BY can reference it by alias.
    # PostgreSQL resolves column aliases from SELECT in ORDER BY, but NOT inside CASE expressions
    # within ORDER BY (BP-TODO). Wrapping in a CTE avoids the UndefinedColumnError.
    "),\n"
    "ranked AS (\n"
    """SELECT dsm.doc_id,
       dsm.title,
       dsm.url,
       dsm.published_at,
       dsm.source_type,
       dsm.source_name,
       dsm.llm_relevance_score,
       dsm.sentiment,
       dsm.impact_score,
       rd.composite_score                                AS routing_score,
       COALESCE(rd.final_routing_tier, rd.routing_tier) AS routing_tier,
       aw.day_t0_score,
       aw.day_t1_score,
       aw.day_t2_score,
       aw.day_t5_score,
       aw.market_impact_score,
"""
    + _DISPLAY_SCORE_CASE.format(
        market="aw.market_impact_score",
        llm="dsm.llm_relevance_score",
        routing="rd.composite_score",
    )
    + """                                                         AS display_relevance_score,
       COUNT(*) OVER()                                   AS total_count
FROM entity_article_ids ea
JOIN  document_source_metadata dsm ON dsm.doc_id = ea.article_id
LEFT JOIN article_windows aw       ON aw.article_id  = ea.article_id
LEFT JOIN routing_decisions rd     ON rd.doc_id      = ea.article_id
WHERE dsm.published_at BETWEEN :start_date AND :end_date
)
SELECT * FROM ranked
ORDER BY
    CASE WHEN :order_by = 'published_at'  THEN ranked.published_at           END DESC,
    CASE WHEN :order_by != 'published_at' THEN ranked.display_relevance_score END DESC
LIMIT :limit OFFSET :offset
"""
)


def _row_to_ranked_article(row: Any, *, include_primary_entity: bool = True) -> RankedArticleData:
    """Map a SQLAlchemy Row to a RankedArticleData DTO."""
    return RankedArticleData(
        article_id=row.doc_id,
        title=row.title,
        url=row.url,
        published_at=row.published_at,
        source_type=row.source_type,
        source_name=row.source_name,
        routing_tier=row.routing_tier,
        routing_score=float(row.routing_score) if row.routing_score is not None else None,
        market_impact_score=float(row.market_impact_score) if row.market_impact_score is not None else None,
        llm_relevance_score=float(row.llm_relevance_score) if row.llm_relevance_score is not None else None,
        display_relevance_score=float(row.display_relevance_score),
        day_t0_score=float(row.day_t0_score) if row.day_t0_score is not None else None,
        day_t1_score=float(row.day_t1_score) if row.day_t1_score is not None else None,
        day_t2_score=float(row.day_t2_score) if row.day_t2_score is not None else None,
        day_t5_score=float(row.day_t5_score) if row.day_t5_score is not None else None,
        primary_entity_id=row.primary_entity_id if include_primary_entity else None,
        primary_entity_symbol=row.primary_entity_symbol if include_primary_entity else None,
        # PLAN-0050 Wave E: sentiment + impact_score from document_source_metadata.
        # hasattr guard: safe against test mocks that don't stub these columns yet.
        sentiment=row.sentiment if hasattr(row, "sentiment") else None,
        impact_score=float(row.impact_score) if hasattr(row, "impact_score") and row.impact_score is not None else None,
    )


class SqlaNewsQueryRepo(NewsQueryPort):
    """SQLAlchemy-backed implementation of NewsQueryPort for ranked news queries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_top_news(
        self,
        hours: int,
        limit: int,
        offset: int,
        min_display_score: float | None,
        routing_tier: str | None,
    ) -> tuple[list[RankedArticleData], int]:
        """Execute Flow C: 3-CTE global top-news query (PRD-0026 §6.7)."""
        # BP-069: pass None directly; IS NULL checks in SQL handle nullable params correctly.
        result = await self._session.execute(
            text(_TOP_NEWS_SQL),
            {
                "hours": hours,
                "routing_tier": routing_tier,
                "min_display_score": min_display_score,
                "limit": limit,
                "offset": offset,
            },
        )
        rows = result.all()
        if not rows:
            return [], 0

        total = int(rows[0].total_count)
        articles = [_row_to_ranked_article(row, include_primary_entity=True) for row in rows]
        return articles, total

    async def get_entity_articles(
        self,
        entity_id: UUID,
        start_date: datetime,
        end_date: datetime,
        order_by: str,
        limit: int,
        offset: int,
        tenant_id: str | None = None,
    ) -> tuple[list[RankedArticleData], int]:
        """Execute Flow D: 2-CTE entity-articles query (PRD-0026 §6.7).

        F-009 Option B: tenant_id filters entity_mentions so only rows belonging
        to the requesting tenant (or legacy NULL rows) are included.
        """
        result = await self._session.execute(
            text(_ENTITY_ARTICLES_SQL),
            {
                "entity_id": str(entity_id),
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
                "order_by": order_by,
                "limit": limit,
                "offset": offset,
            },
        )
        rows = result.all()
        if not rows:
            return [], 0

        total = int(rows[0].total_count)
        # Entity articles: primary_entity_* not populated (entity fixed by path param).
        articles = [_row_to_ranked_article(row, include_primary_entity=False) for row in rows]
        return articles, total
