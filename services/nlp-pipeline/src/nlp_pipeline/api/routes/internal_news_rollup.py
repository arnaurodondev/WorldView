"""GET /internal/v1/instruments/{instrument_id}/news-rollup-7d.

PLAN-0089 Wave L-5a (T-WL5A-04) — read-only rollup consumed by the
S3-side screener sync worker (Wave L-5b) to materialise three columns of
``instrument_intelligence_snapshot``:

  - news_count_7d
  - llm_relevance_7d_max
  - display_relevance_7d_weighted

Split decision: news rollups live in S6 (nlp_db) because
``routing_decisions``, ``document_source_metadata`` and
``article_impact_windows`` are all S6-owned. Contradiction count is hosted
by S7 (see T-WL5A-01).

Auth: ``X-Internal-JWT`` header required; enforced by
``InternalJWTMiddleware`` at the middleware level — no route-level auth
dependency needed.

R9: reads only from ``nlp_db`` (S6's own DB).
R25: API → use case only.
R27: uses the read-replica session via ``get_read_nlp_session``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nlp_pipeline.api.dependencies import get_read_nlp_session
from nlp_pipeline.application.use_cases.news_rollup_7d import GetNewsRollup7dUseCase

router = APIRouter(prefix="/internal/v1", tags=["internal", "rollup"])


# Inline dep alias — keeps the function signature self-documenting and
# matches the convention used by ``internal_costs.router`` (S6 internal route).
ReadSessionDep = Annotated[AsyncSession, Depends(get_read_nlp_session)]


class NewsRollup7dResponse(BaseModel):
    """Response body for the 7-day news rollup endpoint."""

    instrument_id: UUID
    news_count_7d: int = Field(ge=0)
    # MAX over an empty set is NULL — frontend / sync-worker treat as "no signal".
    llm_relevance_7d_max: float | None = None
    display_relevance_7d_weighted: float | None = None


@router.get(
    "/instruments/{instrument_id}/news-rollup-7d",
    response_model=NewsRollup7dResponse,
    summary="[Internal] 7-day news rollup (count + LLM-relevance + display-score) for screener sync",
)
async def get_news_rollup_7d(
    instrument_id: UUID,
    session: ReadSessionDep,
) -> NewsRollup7dResponse:
    """Return the 7-day news rollup for ``instrument_id``.

    Endpoint is non-failing: instruments with no recent articles return
    ``news_count_7d=0`` + null MAX values with HTTP 200. The L-5b nightly
    sync worker treats absence as "no signal" and does not retry.
    """
    rollup = await GetNewsRollup7dUseCase().execute(session=session, instrument_id=instrument_id)
    return NewsRollup7dResponse(
        instrument_id=instrument_id,
        news_count_7d=rollup.news_count_7d,
        llm_relevance_7d_max=rollup.llm_relevance_7d_max,
        display_relevance_7d_weighted=rollup.display_relevance_7d_weighted,
    )
