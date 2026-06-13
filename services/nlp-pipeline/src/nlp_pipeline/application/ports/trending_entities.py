"""TrendingEntitiesQueryPort — abstract port for the NEWS MOMENTUM aggregation.

PLAN-0099 W4 (News Momentum): backs ``GET /api/v1/news/trending-entities``.

The momentum feed answers "which ENTITY is gaining news attention right now,
and is it accelerating?".  Per entity, over a rolling window ``[now-W, now]``, we
count the distinct articles that mention it (the "current" window) and compare
that to the immediately-preceding equal window ``[now-2W, now-W]`` (the "prior"
window).  The difference is the *velocity* / momentum signal — the whole point
of the widget (a 200% surge, +8 articles, etc.), as opposed to raw recency.

This port lives in the APPLICATION layer (R25 / IG-LAYER-002): use cases depend
on this ABC, never on the concrete ``SqlaTrendingEntitiesQueryRepo`` in
infrastructure.  Read-only — implementers MUST NOT write data (R27: the route
wires this onto a ReadOnlyUnitOfWork / read-replica session).

IMPORTANT — cross-database boundary
-----------------------------------
``entity_mentions`` + ``document_source_metadata`` live in **nlp_db** (owned by
S6).  The ticker + canonical_name live in ``canonical_entities`` in
**intelligence_db** — a *separate* PostgreSQL database.  A single SQL JOIN
across the two is therefore impossible.  This port returns rows keyed only by
``resolved_entity_id`` (the data available in nlp_db); the ticker/name
resolution + "must have a ticker" filter (to drop macro noise like NASDAQ /
"U.S." / a newswire) happens in the use case, which holds the intel session too.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class TrendingEntityRow:
    """One entity's news-momentum aggregate over the current window (nlp_db only).

    All fields here are derivable from nlp_db alone — there is intentionally NO
    ticker/name here (that lives in intelligence_db and is joined in the use
    case).  ``top_article_*`` describe the entity's single most relevant recent
    article in the current window (highest ``display_relevance_score``), which
    the widget renders as the entity's headline.
    """

    entity_id: UUID
    # Distinct articles mentioning this entity in the CURRENT window [now-W, now].
    count: int
    # Distinct articles in the PRIOR equal window [now-2W, now-W] — the baseline
    # for the momentum/velocity comparison.
    prior_count: int
    # The most relevant recent article for this entity in the current window.
    # All top_article_* fields are None only if the entity somehow has a count
    # but no joinable document_source_metadata row (defensive; should not happen).
    top_article_id: UUID | None
    top_article_title: str | None
    top_article_url: str | None
    top_article_published_at: datetime | None
    # Normalised in document_source_metadata: "positive"|"negative"|"neutral"|"mixed"|null.
    top_article_sentiment: str | None
    # The honest composite relevance (PRD-0026 §6.5) of the top article, 0-1.
    top_article_relevance: float | None


class TrendingEntitiesQueryPort(ABC):
    """Port for the per-entity news-momentum aggregation (read-only).

    Concrete implementation: ``SqlaTrendingEntitiesQueryRepo`` in infrastructure.
    """

    @abstractmethod
    async def get_trending_entities(
        self,
        window_hours: int,
        candidate_limit: int,
    ) -> list[TrendingEntityRow]:
        """Return per-entity momentum rows over the given window.

        Aggregates ``entity_mentions`` joined to ``document_source_metadata``:
          * CURRENT window  = ``published_at`` in ``[now - window_hours, now]``
          * PRIOR window    = ``published_at`` in ``[now - 2*window_hours, now - window_hours]``

        Args:
            window_hours: Size of one momentum window in hours (24 | 72 | 168).
            candidate_limit: Max entities to return from the DB layer, BEFORE the
                use-case ticker filter + momentum ranking.  Over-fetch (e.g. 200)
                so that after dropping macro-noise entities without a ticker we
                still have enough tradeable names to fill the widget.

        Returns:
            A list of ``TrendingEntityRow`` ordered by current ``count`` DESC
            (the use case re-ranks by momentum).  Only entities with a non-null
            ``resolved_entity_id`` and ``count >= 1`` in the current window are
            included; the minimum-count floor for ranking is applied by the use
            case so the SQL stays a pure aggregate.
        """
        ...
