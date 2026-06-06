"""Analytics endpoints for S6 NLP Pipeline (PLAN-0091 Wave E-1).

GET /api/v1/entities/{entity_id}/sentiment-timeseries?days=90
  Returns daily sentiment aggregates for a canonical entity over the last N days.
  Protected by InternalJWTMiddleware (app-wide) + require_internal_jwt Depends (per-route).
  tenant_id is read from request.state (set by InternalJWTMiddleware) — never from the
  request body or query string (PLAN-0087 security pattern).
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Query, Request

from nlp_pipeline.api.dependencies import InternalJwtAuthDep, SentimentTimeseriesUseCaseDep

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["analytics"])


@router.get("/entities/{entity_id}/sentiment-timeseries")
async def get_entity_sentiment_timeseries(
    entity_id: UUID,
    request: Request,
    use_case: SentimentTimeseriesUseCaseDep,
    _auth: InternalJwtAuthDep,
    days: int = Query(default=90, ge=1, le=365, description="Look-back window in days (1-365)"),
) -> dict[str, object]:
    """Daily sentiment + relevance aggregates for a canonical entity.

    Groups document_source_metadata by calendar day (UTC) after filtering by
    entity_mentions.resolved_entity_id AND em.tenant_id (from JWT).
    Returns article_count, avg_relevance, positive_ratio, negative_ratio,
    avg_impact_score per day.

    Returns an empty points list when no articles have been processed yet
    for this entity in the requested window.
    """
    # F-301/F-410: tenant_id MUST come from the JWT (request.state), never
    # from query params.  Follow the PLAN-0087 pattern from search.py.
    auth_tenant_raw = getattr(request.state, "tenant_id", None)
    tenant_id: str | None
    if isinstance(auth_tenant_raw, str) and auth_tenant_raw:
        try:
            UUID(auth_tenant_raw)
            tenant_id = auth_tenant_raw
        except ValueError:
            tenant_id = None
    else:
        tenant_id = None

    log.debug("get_entity_sentiment_timeseries", entity_id=str(entity_id), days=days, has_tenant=tenant_id is not None)
    points = await use_case.execute(entity_id=entity_id, days=days, tenant_id=tenant_id)
    return {
        "entity_id": str(entity_id),
        "days": days,
        "points": points,
    }
