"""GetNewsRollup7dUseCase — PLAN-0089 Wave L-5a (T-WL5A-04).

Returns 3 rollup fields for the S3-side screener sync worker (Wave L-5b)
to materialise into ``instrument_intelligence_snapshot``:

- ``news_count_7d``               — COUNT(DISTINCT doc_id) of articles
  mentioning the entity in the last 7 days
- ``llm_relevance_7d_max``        — MAX(document_source_metadata.llm_relevance_score)
  over those articles
- ``display_relevance_7d_weighted`` — MAX(display_relevance_score) using
  the PRD-0026 §6.5 4-branch CASE formula (market+llm+routing weights)

Split rationale (per L-5 scope investigation): the canonical data path for
news routing lives in S6's nlp_db (``routing_decisions``,
``document_source_metadata``, ``article_impact_windows``), so the 3 news
fields are sourced here. The 4th L-5 rollup field
(``recent_contradiction_count``) is hosted by S7 (T-WL5A-01) because
contradictions live in intelligence_db.

Entity ↔ instrument linkage: we reuse the existing two-leg UNION pattern
from BP-606's ``_ENTITY_ARTICLES_SQL`` so we catch both normalised
``entity_mentions`` rows AND denormalised ``chunks.entity_mentions``
JSONB containment (the MSTR-class entity-drift fix). ``:entity_id`` is
the instrument_id, equal to ``canonical_entities.entity_id`` for
instrument-type entities (PLAN-0057 F-DS-03).

R9: reads only from ``nlp_db`` (S6's own DB).
R25: API → use case only.
R27: caller wires a read-only AsyncSession.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# Hard-coded 7-day window — interpolated as a literal because Postgres does
# not accept a bound parameter inside an INTERVAL literal. The value is a
# module constant (no user input) so injection is impossible.
_WINDOW_DAYS = 7


# Mirror the PRD-0026 §6.5 4-branch display_relevance CASE expression. This
# duplicates ``_DISPLAY_SCORE_CASE`` in ``news_query.py`` so that the
# rollup query stays self-contained; if the formula changes both call sites
# must be updated in lock-step.
_DISPLAY_SCORE_CASE = """\
    CASE
        WHEN ami.market_impact_score > 0 AND dsm.llm_relevance_score IS NOT NULL
            THEN 0.50 * ami.market_impact_score + 0.40 * dsm.llm_relevance_score
                 + 0.10 * COALESCE(rd.composite_score, 0.0)
        WHEN ami.market_impact_score > 0
            THEN 0.70 * ami.market_impact_score + 0.30 * COALESCE(rd.composite_score, 0.0)
        WHEN dsm.llm_relevance_score IS NOT NULL
            THEN 0.60 * dsm.llm_relevance_score + 0.40 * COALESCE(rd.composite_score, 0.0)
        ELSE COALESCE(rd.composite_score, 0.0) * 0.40
    END"""


# Two-leg discovery (BP-606): both normalised entity_mentions table AND
# denormalised chunks.entity_mentions JSONB containment. R35: include
# legacy NULL-tenant rows + the requesting tenant + the PUBLIC sentinel.
# For internal rollup queries we treat tenant_id as wildcard (NULL OR any
# tenant OR public) because the screener result is public-facing.
# S608 suppressed: only the module-constant _WINDOW_DAYS is interpolated; no
# user input flows into the SQL string. ``:entity_id`` is a bound parameter.
_NEWS_ROLLUP_SQL_TEMPLATE = """\
WITH entity_article_ids AS (
    SELECT DISTINCT em.doc_id AS article_id
    FROM entity_mentions em
    WHERE em.resolved_entity_id = :entity_id
    UNION
    SELECT DISTINCT c.doc_id AS article_id
    FROM chunks c
    WHERE c.entity_mentions @> jsonb_build_array(
        jsonb_build_object('entity_id', CAST(:entity_id AS TEXT))
    )
),
article_windows AS (
    SELECT article_id,
           GREATEST(
               MAX(CASE WHEN window_type = 'day_t0' THEN impact_score END),
               MAX(CASE WHEN window_type = 'day_t1' THEN impact_score END)
           ) AS market_impact_score
    FROM article_impact_windows
    WHERE article_id IN (SELECT article_id FROM entity_article_ids)
    GROUP BY article_id
),
scored AS (
    SELECT dsm.doc_id,
           dsm.llm_relevance_score,
           ami.market_impact_score,
           rd.composite_score AS routing_score,
__DISPLAY_SCORE_CASE__ AS display_relevance_score
    FROM entity_article_ids ea
    JOIN document_source_metadata dsm ON dsm.doc_id = ea.article_id
    LEFT JOIN article_windows ami      ON ami.article_id = ea.article_id
    LEFT JOIN routing_decisions rd     ON rd.doc_id      = ea.article_id
    WHERE dsm.published_at >= now() - INTERVAL '__WINDOW_DAYS__ days'::interval
)
SELECT COUNT(*)                              AS news_count_7d,
       MAX(llm_relevance_score)              AS llm_relevance_7d_max,
       MAX(display_relevance_score)          AS display_relevance_7d_weighted
FROM scored
"""

# Hand-rolled substitution avoids .format() {} collisions with future SQL
# braces and keeps the linter happy (no string-concat in execute()).
_NEWS_ROLLUP_SQL = _NEWS_ROLLUP_SQL_TEMPLATE.replace(
    "__DISPLAY_SCORE_CASE__",
    _DISPLAY_SCORE_CASE,
).replace("__WINDOW_DAYS__", str(_WINDOW_DAYS))


@dataclass(frozen=True)
class NewsRollup7d:
    """Small JSON-friendly DTO returned by the use case."""

    news_count_7d: int
    llm_relevance_7d_max: float | None
    display_relevance_7d_weighted: float | None


class GetNewsRollup7dUseCase:
    """7-day news + display-relevance rollup for one instrument."""

    async def execute(
        self,
        session: AsyncSession,
        instrument_id: UUID,
    ) -> NewsRollup7d:
        """Return the 3-field rollup for ``instrument_id``."""
        result = await session.execute(
            text(_NEWS_ROLLUP_SQL),
            {"entity_id": str(instrument_id)},
        )
        row = result.fetchone()
        if row is None:
            # Defensive — COUNT/MAX always returns one row, even when empty.
            return NewsRollup7d(0, None, None)

        return NewsRollup7d(
            news_count_7d=int(row[0] or 0),
            llm_relevance_7d_max=float(row[1]) if row[1] is not None else None,
            display_relevance_7d_weighted=float(row[2]) if row[2] is not None else None,
        )
