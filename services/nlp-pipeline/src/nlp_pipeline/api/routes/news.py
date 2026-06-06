"""REST API endpoints for ranked news feeds (PRD-0026 §6.2).

GET /api/v1/news/top
  Returns globally top-N articles ranked by display_relevance_score within a
  rolling time window.  No authentication required (consistent with other S6
  read endpoints — internal service, protected by InternalJWTMiddleware).

This router is registered in app.py alongside the existing signal/entity routers.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from nlp_pipeline.api.dependencies import NewsQueryRepoDep
from nlp_pipeline.api.schemas import ImpactWindows, RankedArticleResponse, RankedNewsResponse
from nlp_pipeline.application.use_cases.signals import GetTopNewsUseCase

router = APIRouter(prefix="/api/v1", tags=["news"])


def _to_response(item: object) -> RankedArticleResponse:
    """Map a RankedArticleData DTO to the API response schema."""
    # Build ImpactWindows only when at least one window score is present.
    any_window = any(
        getattr(item, f) is not None for f in ("day_t0_score", "day_t1_score", "day_t2_score", "day_t5_score")
    )
    return RankedArticleResponse(
        article_id=item.article_id,  # type: ignore[attr-defined]
        title=item.title,  # type: ignore[attr-defined]
        url=item.url,  # type: ignore[attr-defined]
        published_at=item.published_at,  # type: ignore[attr-defined]
        source_type=item.source_type,  # type: ignore[attr-defined]
        source_name=item.source_name,  # type: ignore[attr-defined]
        routing_tier=item.routing_tier,  # type: ignore[attr-defined]
        routing_score=item.routing_score,  # type: ignore[attr-defined]
        market_impact_score=item.market_impact_score,  # type: ignore[attr-defined]
        llm_relevance_score=item.llm_relevance_score,  # type: ignore[attr-defined]
        display_relevance_score=item.display_relevance_score,  # type: ignore[attr-defined]
        primary_entity_id=item.primary_entity_id,  # type: ignore[attr-defined]
        primary_entity_symbol=item.primary_entity_symbol,  # type: ignore[attr-defined]
        impact_windows=ImpactWindows(
            day_t0=item.day_t0_score,  # type: ignore[attr-defined]
            day_t1=item.day_t1_score,  # type: ignore[attr-defined]
            day_t2=item.day_t2_score,  # type: ignore[attr-defined]
            day_t5=item.day_t5_score,  # type: ignore[attr-defined]
        )
        if any_window
        else None,
        # PLAN-0050 Wave E: forward sentiment and impact_score from the DTO.
        # These are null until the scoring workers process the article.
        sentiment=item.sentiment,  # type: ignore[attr-defined]
        impact_score=item.impact_score,  # type: ignore[attr-defined]
    )


@router.get("/news/top", response_model=RankedNewsResponse)
async def get_top_news(
    repo: NewsQueryRepoDep,
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window in hours (1-168)"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    min_display_score: float | None = Query(default=None, ge=0.0, le=1.0),
    routing_tier: str | None = Query(
        default=None,
        pattern="^(LIGHT|MEDIUM|DEEP)$",
        description="Filter by effective routing tier",
    ),
    tickers: str | None = Query(
        default=None,
        description="Comma-separated ticker symbols to filter by primary entity (e.g. AAPL,MSFT)",
    ),
) -> RankedNewsResponse:
    """Return globally top-ranked articles within a rolling time window.

    Articles are ranked by ``display_relevance_score`` (DESC), a composite of
    market price impact, LLM relevance, and routing score computed at query time.

    When ``tickers`` is supplied only articles whose primary entity symbol matches
    one of the given tickers are returned; symbols are normalised to upper-case.
    """
    # Split and normalise the comma-separated ticker string into a deduplicated list.
    # Empty string / whitespace-only tokens are dropped so "AAPL, ,MSFT" → ["AAPL", "MSFT"].
    ticker_list: list[str] | None = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else None
    articles, total = await GetTopNewsUseCase().execute(
        repo=repo,
        hours=hours,
        limit=limit,
        offset=offset,
        min_display_score=min_display_score,
        routing_tier=routing_tier,
        tickers=ticker_list,
    )
    return RankedNewsResponse(
        articles=[_to_response(a) for a in articles],
        total=total,
    )
