"""News response schemas.

WHY: These Pydantic models mirror the TypeScript interfaces in
apps/worldview-web/types/api.ts (RankedArticle, RankedNewsResponse).
GET /v1/news/top proxies S6's ranked news endpoint which returns
{articles: RankedArticle[], total: int} — not the legacy NewsResponse shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NewsArticle(BaseModel):
    """A single ranked news article from S6 (PRD-0026).

    Mirrors the RankedArticle TypeScript interface in types/api.ts.
    WHY so many optional fields: routing_score/llm_relevance/market_impact
    are absent for LIGHT-tier articles (skipped by S6's scoring pipeline)
    and for very recent articles not yet through the impact-window computation.
    """

    model_config = ConfigDict(extra="allow")

    article_id: str
    title: str | None = None
    url: str | None = None
    published_at: str | None = None
    source_type: str | None = None
    source_name: str | None = None
    display_relevance_score: float | None = None
    market_impact_score: float | None = None
    llm_relevance_score: float | None = None
    routing_tier: str | None = None
    routing_score: float | None = None
    primary_entity_id: str | None = None
    primary_entity_symbol: str | None = None


class NewsTopResponse(BaseModel):
    """Response from GET /v1/news/top (PRD-0026 §6.2).

    Mirrors the RankedNewsResponse TypeScript interface in types/api.ts.
    WHY no offset/limit: S6's ranked endpoint uses total-count-based
    pagination — clients track offset locally using total.
    """

    model_config = ConfigDict(extra="allow")

    articles: list[NewsArticle] = []
    total: int = 0
