"""GetTrendingEntitiesUseCase — the NEWS MOMENTUM ranking (PLAN-0099 W4).

Combines two read-only sources across the DB boundary:
  1. ``TrendingEntitiesQueryPort`` (nlp_db) — per-entity current/prior article
     counts + each entity's top recent article.
  2. ``CanonicalEntityPort`` (intelligence_db) — ticker + canonical_name.

Why the join lives here (not in SQL): ``entity_mentions`` is in nlp_db and
``canonical_entities`` is in a *separate* database (intelligence_db), so a single
SQL JOIN is impossible.  The use case fetches the candidate entity_ids from
nlp_db, resolves their tickers via a single ``batch_get`` against intelligence_db,
DROPS entities without a ticker (macro noise: NASDAQ, NYSE, "U.S.", newswires —
nothing the user can navigate to), then ranks the survivors by MOMENTUM.

Momentum ranking
----------------
delta      = count - prior_count                       (absolute velocity)
delta_pct  = 100 * delta / max(prior_count, 1)         (relative surge)

We rank by ``delta_pct`` DESC (the surge — the whole point), but only for
entities at or above a minimum current-count FLOOR (``min_count``, default 2) so
a noisy 0→1 / 1→2 blip can't dominate a genuine surge.  Ties on delta_pct break
by raw ``count`` DESC (more coverage = more notable).  R25: depends only on
ports.  No infrastructure imports.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from nlp_pipeline.application.ports.canonical_entity import CanonicalEntityPort
    from nlp_pipeline.application.ports.trending_entities import TrendingEntitiesQueryPort

# Over-fetch this many candidate entities from nlp_db before the ticker filter.
# The top raw-count entities are dominated by macro noise without a ticker
# (live: NASDAQ/NYSE/S&P 500/"U.S."/Wall Street occupy most of the top 12), so
# we must pull a wide candidate pool to still fill the widget with tradeable
# names after filtering.  200 is comfortably wide vs. the ~30 limit served.
_CANDIDATE_OVERFETCH = 200


@dataclasses.dataclass(frozen=True)
class TrendingEntityData:
    """Application-layer DTO for one NEWS MOMENTUM row (fully resolved).

    This is the shape the API layer maps to the response schema. Every row is a
    tradeable entity (``ticker`` is guaranteed non-null) with a momentum signal
    and a clickable headline.
    """

    entity_id: UUID
    ticker: str
    name: str
    count: int
    prior_count: int
    delta: int
    delta_pct: float
    # True when there is NO prior-window coverage (prior_count == 0). In that case a
    # percentage surge is undefined — the API/UI should render a "NEW" badge instead of
    # a fabricated ``count * 100%``. See the delta_pct computation in ``execute``.
    is_new: bool
    top_article_id: UUID | None
    top_article_title: str | None
    top_article_url: str | None
    top_article_published_at: datetime | None
    top_article_sentiment: str | None
    top_article_relevance: float | None


class GetTrendingEntitiesUseCase:
    """Rank tradeable entities by news-coverage momentum over a window."""

    async def execute(
        self,
        *,
        trending_repo: TrendingEntitiesQueryPort,
        canonical_repo: CanonicalEntityPort,
        window_hours: int,
        limit: int,
        min_count: int = 2,
    ) -> list[TrendingEntityData]:
        """Return up to ``limit`` momentum rows, ranked by surge.

        Args:
            trending_repo: nlp_db aggregation port.
            canonical_repo: intelligence_db ticker/name resolution port.
            window_hours: Momentum window size (24 | 72 | 168).
            limit: Max rows to return after ranking.
            min_count: Minimum CURRENT-window article count for a row to be
                eligible for ranking (default 2) — stops a 1→2 blip from
                topping the feed on delta_pct alone.
        """
        # 1. Pull the candidate aggregates from nlp_db (over-fetched).
        rows = await trending_repo.get_trending_entities(
            window_hours=window_hours,
            candidate_limit=_CANDIDATE_OVERFETCH,
        )
        if not rows:
            return []

        # 2. Resolve tickers + names in a single intelligence_db round-trip.
        entity_ids = [r.entity_id for r in rows]
        canonical = await canonical_repo.batch_get(entity_ids)

        # 3. Build resolved rows, DROPPING:
        #    - entities missing from canonical_entities entirely, and
        #    - entities with no ticker (macro noise the user can't navigate to),
        #    - entities below the min-count floor (noise).
        results: list[TrendingEntityData] = []
        for r in rows:
            meta = canonical.get(r.entity_id)
            if meta is None:
                continue
            ticker = meta.get("ticker")
            # Guard against both NULL and empty-string tickers in the data.
            if not ticker or not str(ticker).strip():
                continue
            if r.count < min_count:
                continue

            delta = r.count - r.prior_count
            # delta_pct: relative surge vs the prior equal window. When there is NO
            # prior coverage (prior_count == 0) a percentage is UNDEFINED — the old code
            # floored the denominator at 1, turning a 0→N jump into a fabricated N*100%
            # surge (e.g. 0→14 → "1400%"). During a news-ingestion gap the prior window
            # is empty for EVERY entity, so the whole panel read as an explosive rally.
            # Instead we flag the row is_new and emit delta_pct=0.0; the API/UI renders a
            # "NEW" badge. Real surges (prior_count > 0) keep an honest percentage.
            is_new = r.prior_count <= 0
            delta_pct = 0.0 if is_new else 100.0 * delta / r.prior_count

            results.append(
                TrendingEntityData(
                    entity_id=r.entity_id,
                    ticker=str(ticker).strip().upper(),
                    # canonical_name is NOT NULL in the schema, but guard anyway.
                    name=str(meta.get("canonical_name") or ticker),
                    count=r.count,
                    prior_count=r.prior_count,
                    delta=delta,
                    delta_pct=delta_pct,
                    is_new=is_new,
                    top_article_id=r.top_article_id,
                    top_article_title=r.top_article_title,
                    top_article_url=r.top_article_url,
                    top_article_published_at=r.top_article_published_at,
                    top_article_sentiment=r.top_article_sentiment,
                    top_article_relevance=r.top_article_relevance,
                )
            )

        # 4. Rank: real surges (prior coverage) first, ordered by delta_pct; then
        #    new-coverage rows ordered by raw volume. `not x.is_new` is True(1) for real
        #    rows and False(0) for new rows, so with reverse=True the real surges lead.
        #    New rows have delta_pct=0.0, so within them the tie-break is raw count.
        results.sort(key=lambda x: (not x.is_new, x.delta_pct, x.count), reverse=True)
        return results[:limit]
