"""Analytics endpoints for S6 NLP Pipeline (PLAN-0091 Wave E-1).

GET /api/v1/entities/{entity_id}/sentiment-timeseries?days=90
  Returns daily sentiment aggregates for a canonical entity over the last N days.
  Requires InternalJWTMiddleware authentication.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Query

from nlp_pipeline.api.dependencies import SentimentTimeseriesRepoDep
from nlp_pipeline.application.use_cases.get_entity_sentiment_timeseries import (
    GetEntitySentimentTimeseriesUseCase,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["analytics"])


@router.get("/entities/{entity_id}/sentiment-timeseries")
async def get_entity_sentiment_timeseries(
    entity_id: UUID,
    repo: SentimentTimeseriesRepoDep,
    days: int = Query(default=90, ge=1, le=365, description="Look-back window in days (1-365)"),
) -> dict[str, object]:
    """Daily sentiment + relevance aggregates for a canonical entity.

    Groups document_source_metadata by calendar day (UTC) after filtering by
    entity_mentions.resolved_entity_id.  Returns article_count, avg_relevance,
    positive_ratio, negative_ratio, avg_impact_score per day.

    Returns an empty points list when no articles have been processed yet
    for this entity in the requested window.
    """
    log.debug("get_entity_sentiment_timeseries", entity_id=str(entity_id), days=days)
    uc = GetEntitySentimentTimeseriesUseCase()
    points = await uc.execute(repo=repo, entity_id=entity_id, days=days)
    return {
        "entity_id": str(entity_id),
        "days": days,
        "points": points,
    }
