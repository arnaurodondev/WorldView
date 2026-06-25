"""SQLAlchemy implementation of TrendingEntitiesQueryPort (NEWS MOMENTUM).

PLAN-0099 W4. Backs ``GET /api/v1/news/trending-entities`` — the per-entity
news-momentum aggregation for the dashboard "NEWS MOMENTUM" widget.

The query runs entirely against **nlp_db** (``entity_mentions`` +
``document_source_metadata`` + ``routing_decisions``).  Ticker/name resolution
and the "must have a ticker" macro-noise filter happen in the use case (which
holds the separate intelligence_db session) — see ``TrendingEntitiesQueryPort``.

SQL shape (single round-trip)
-----------------------------
  cur     — distinct article count per entity in [now-W, now]   (the momentum numerator)
  prior   — distinct article count per entity in [now-2W, now-W] (the baseline)
  scored  — every (entity, article) pair in the CURRENT window with the article's
            display_relevance_score computed at query time (PRD-0026 §6.5),
            ranked per entity so we can pick each entity's TOP article in one pass.
  final   — join cur + prior + the rank-1 (top) article per entity.

We over-fetch ``candidate_limit`` entities ordered by current count DESC so the
use case still has enough tradeable (ticker'd) names after dropping macro noise.
Ranking by momentum (delta_pct, min-count floor) is done in the use case so the
SQL stays a pure, cacheable aggregate.

display_relevance_score reuses the EXACT CASE expression + window-pivot fragment
from ``news_query.py`` (the canonical PRD-0026 §6.5 formula) so the entity's
headline relevance matches what the rest of the platform shows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from nlp_pipeline.application.ports.trending_entities import (
    TrendingEntitiesQueryPort,
    TrendingEntityRow,
)
from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import (
    _DISPLAY_SCORE_CASE,
    _WINDOW_PIVOT_FRAGMENT,
    _normalise_finnhub_api_url,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Trending-entities SQL — NEWS MOMENTUM aggregation (PLAN-0099 W4)
# ---------------------------------------------------------------------------
#
# Parameters: :window_hours (int), :limit (int).
# now() is evaluated once per statement, so the current and prior windows are
# anchored to the same instant — no boundary drift between the two CTEs.
_TRENDING_ENTITIES_SQL = (
    # ── article_market_impact: pivot impact windows to one row per article ──
    "WITH article_market_impact AS (\n" + _WINDOW_PIVOT_FRAGMENT + "    GROUP BY article_id\n"
    "),\n"
    # ── cur: distinct articles per entity in the CURRENT window [now-W, now] ──
    # COUNT(DISTINCT doc_id) so an article that mentions an entity many times
    # still counts once — "articles", not "mentions" (the user's unit).
    "cur AS (\n"
    "    SELECT em.resolved_entity_id AS entity_id,\n"
    "           COUNT(DISTINCT em.doc_id) AS cnt\n"
    "    FROM entity_mentions em\n"
    "    JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id\n"
    "    WHERE em.resolved_entity_id IS NOT NULL\n"
    "      AND dsm.published_at >= now() - :window_hours * interval '1 hour'\n"
    "      AND dsm.published_at <= now()\n"
    "    GROUP BY em.resolved_entity_id\n"
    "),\n"
    # ── prior: distinct articles per entity in [now-2W, now-W] (the baseline) ──
    "prior AS (\n"
    "    SELECT em.resolved_entity_id AS entity_id,\n"
    "           COUNT(DISTINCT em.doc_id) AS cnt\n"
    "    FROM entity_mentions em\n"
    "    JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id\n"
    "    WHERE em.resolved_entity_id IS NOT NULL\n"
    "      AND dsm.published_at >= now() - (2 * :window_hours) * interval '1 hour'\n"
    "      AND dsm.published_at <  now() - :window_hours * interval '1 hour'\n"
    "    GROUP BY em.resolved_entity_id\n"
    "),\n"
    # ── candidates: top entities by current count (over-fetch for the filter) ──
    # Restrict the expensive top-article scan to just the candidate set.
    "candidates AS (\n"
    "    SELECT entity_id, cnt FROM cur ORDER BY cnt DESC LIMIT :limit\n"
    "),\n"
    # ── scored: every (entity, article) in the current window with relevance ──
    # display_relevance_score is computed at query time using the canonical
    # PRD-0026 §6.5 CASE expression; ROW_NUMBER picks each entity's TOP article.
    "scored AS (\n"
    "    SELECT em.resolved_entity_id AS entity_id,\n"
    "           dsm.doc_id,\n"
    "           dsm.title,\n"
    "           dsm.url,\n"
    "           dsm.published_at,\n"
    "           dsm.sentiment,\n"
    + _DISPLAY_SCORE_CASE.format(
        market="ami.market_impact_score",
        llm="dsm.llm_relevance_score",
        routing="rd.composite_score",
    )
    + " AS display_relevance_score,\n"
    "           ROW_NUMBER() OVER (\n"
    "               PARTITION BY em.resolved_entity_id\n"
    "               ORDER BY (\n"
    + _DISPLAY_SCORE_CASE.format(
        market="ami.market_impact_score",
        llm="dsm.llm_relevance_score",
        routing="rd.composite_score",
    )
    + "               ) DESC NULLS LAST, dsm.published_at DESC\n"
    "           ) AS rn\n"
    "    FROM entity_mentions em\n"
    "    JOIN candidates cnd ON cnd.entity_id = em.resolved_entity_id\n"
    "    JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id\n"
    "    LEFT JOIN article_market_impact ami ON ami.article_id = dsm.doc_id\n"
    "    LEFT JOIN routing_decisions rd ON rd.doc_id = dsm.doc_id\n"
    "    WHERE dsm.published_at >= now() - :window_hours * interval '1 hour'\n"
    "      AND dsm.published_at <= now()\n"
    ")\n"
    # ── final: cur + prior + the rank-1 (top) article per entity ──
    "SELECT cnd.entity_id,\n"
    "       cnd.cnt AS count,\n"
    "       COALESCE(prior.cnt, 0) AS prior_count,\n"
    "       s.doc_id AS top_article_id,\n"
    "       s.title AS top_article_title,\n"
    "       s.url AS top_article_url,\n"
    "       s.published_at AS top_article_published_at,\n"
    "       s.sentiment AS top_article_sentiment,\n"
    "       s.display_relevance_score AS top_article_relevance\n"
    "FROM candidates cnd\n"
    "LEFT JOIN prior ON prior.entity_id = cnd.entity_id\n"
    "LEFT JOIN scored s ON s.entity_id = cnd.entity_id AND s.rn = 1\n"
    "ORDER BY cnd.cnt DESC\n"
)


def _row_to_trending_entity(row: Any) -> TrendingEntityRow:
    """Map a SQLAlchemy Row to a TrendingEntityRow DTO.

    Mirrors ``news_query._row_to_ranked_article``'s defensive None-handling and
    reuses ``_normalise_finnhub_api_url`` so the headline link is clickable.
    """
    return TrendingEntityRow(
        entity_id=UUID(str(row.entity_id)),
        count=int(row.count),
        prior_count=int(row.prior_count),
        top_article_id=UUID(str(row.top_article_id)) if row.top_article_id is not None else None,
        top_article_title=row.top_article_title,
        top_article_url=_normalise_finnhub_api_url(row.top_article_url),
        top_article_published_at=row.top_article_published_at,
        top_article_sentiment=row.top_article_sentiment,
        top_article_relevance=(float(row.top_article_relevance) if row.top_article_relevance is not None else None),
    )


class SqlaTrendingEntitiesQueryRepo(TrendingEntitiesQueryPort):
    """SQLAlchemy-backed implementation of TrendingEntitiesQueryPort (read-only)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_trending_entities(
        self,
        window_hours: int,
        candidate_limit: int,
    ) -> list[TrendingEntityRow]:
        """Execute the NEWS MOMENTUM aggregation; see the port docstring."""
        result = await self._session.execute(
            text(_TRENDING_ENTITIES_SQL),
            {"window_hours": window_hours, "limit": candidate_limit},
        )
        rows = result.all()
        return [_row_to_trending_entity(row) for row in rows]
