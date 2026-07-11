"""REST endpoint for the NEWS MOMENTUM feed (PLAN-0099 W4).

GET /api/v1/news/trending-entities
  Returns, per tradeable entity, its news-coverage MOMENTUM over a rolling
  window: how many distinct articles mention it now, how that compares to the
  prior equal window (the surge), and its single most relevant recent headline.

  Ranked by momentum (surge), not raw recency — this is the difference from
  ``/news/top`` (which is global recent articles).  Only entities with a ticker
  are returned (macro noise like NASDAQ / "U.S." / newswires is dropped).

  No authentication required, consistent with the other S6 read endpoints
  (internal service, protected by InternalJWTMiddleware at the edge).

This router is registered in app.py alongside the existing news router.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from nlp_pipeline.api.dependencies import CanonicalEntityRepoDep, TrendingEntitiesRepoDep
from nlp_pipeline.application.use_cases.trending_entities import (
    GetTrendingEntitiesUseCase,
    TrendingEntityData,
)

router = APIRouter(prefix="/api/v1", tags=["news"])


class TrendingTopArticle(BaseModel):
    """The entity's most relevant recent headline (clickable in the widget)."""

    id: UUID | None = None
    title: str | None = None
    url: str | None = None
    source: str | None = None
    published_at: datetime | None = None
    # "positive" | "negative" | "neutral" | "mixed" | null
    sentiment: str | None = None
    # Honest composite relevance (PRD-0026 §6.5), 0-1.
    relevance: float | None = None


class TrendingEntityResponse(BaseModel):
    """One NEWS MOMENTUM row — a tradeable entity with a momentum signal."""

    entity_id: UUID
    ticker: str
    name: str
    # Distinct articles mentioning the entity in the current window.
    count: int
    # Distinct articles in the prior equal window (the baseline).
    prior_count: int
    # Absolute velocity: count - prior_count.
    delta: int
    # Relative surge: 100 * delta / prior_count when prior_count > 0, else 0.0.
    delta_pct: float
    # True when prior_count == 0 (no baseline). Clients should render a "NEW" badge
    # instead of delta_pct, which is meaningless (0.0) for new-coverage rows.
    is_new: bool = False
    top_article: TrendingTopArticle | None = None


class TrendingEntitiesResponse(BaseModel):
    """Envelope for the trending-entities feed."""

    entities: list[TrendingEntityResponse]
    window_hours: int


def _source_from_url(url: str | None) -> str | None:
    """Derive a short publisher label from an article URL host.

    ``document_source_metadata.source_name`` is empty in the live data, so the
    URL host is the most reliable publisher signal. Mirrors the gateway's
    ``_source_from_url`` so both layers label sources identically.
    """
    if not url:
        return None
    from urllib.parse import urlparse

    try:
        host = (urlparse(url).hostname or "").lower()
    except (ValueError, TypeError):
        return None
    if not host:
        return None
    for prefix in ("www.", "m.", "uk.", "finance.", "markets."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    label = host.split(".")[0] if host else ""
    return label or None


def _to_response(item: TrendingEntityData) -> TrendingEntityResponse:
    """Map a TrendingEntityData DTO to the API response schema."""
    top: TrendingTopArticle | None = None
    if item.top_article_id is not None or item.top_article_title is not None:
        top = TrendingTopArticle(
            id=item.top_article_id,
            title=item.top_article_title,
            url=item.top_article_url,
            source=_source_from_url(item.top_article_url),
            published_at=item.top_article_published_at,
            sentiment=item.top_article_sentiment,
            relevance=item.top_article_relevance,
        )
    return TrendingEntityResponse(
        entity_id=item.entity_id,
        ticker=item.ticker,
        name=item.name,
        count=item.count,
        prior_count=item.prior_count,
        delta=item.delta,
        delta_pct=item.delta_pct,
        is_new=item.is_new,
        top_article=top,
    )


@router.get("/news/trending-entities", response_model=TrendingEntitiesResponse)
async def get_trending_entities(
    trending_repo: TrendingEntitiesRepoDep,
    canonical_repo: CanonicalEntityRepoDep,
    window_hours: int = Query(
        default=24,
        description="Momentum window in hours. One of 24 (24H) | 72 (3D) | 168 (1W).",
    ),
    limit: int = Query(default=30, ge=1, le=100),
    min_count: int = Query(
        default=2,
        ge=1,
        le=50,
        description="Minimum current-window article count for an entity to rank (anti-noise floor).",
    ),
) -> TrendingEntitiesResponse:
    """Return tradeable entities ranked by news-coverage momentum.

    ``window_hours`` is snapped to the nearest allowed UI option (24 | 72 | 168);
    any other value falls back to 24. The response echoes the resolved
    ``window_hours`` so the caller can confirm which window it got.
    """
    # Snap to the allowed UI windows so an arbitrary value can't reach the SQL.
    resolved_window = window_hours if window_hours in (24, 72, 168) else 24

    items = await GetTrendingEntitiesUseCase().execute(
        trending_repo=trending_repo,
        canonical_repo=canonical_repo,
        window_hours=resolved_window,
        limit=limit,
        min_count=min_count,
    )
    return TrendingEntitiesResponse(
        entities=[_to_response(i) for i in items],
        window_hours=resolved_window,
    )
