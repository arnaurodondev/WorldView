"""GET /internal/v1/instruments/{instrument_id}/intelligence-rollup-7d.

PLAN-0089 Wave L-5a — read-only rollup consumed by the S3-side screener
sync worker (Wave L-5b) to materialise the
``instrument_intelligence_snapshot.recent_contradiction_count`` column.

Auth: ``X-Internal-JWT`` header required; enforced by
``InternalJWTMiddleware`` at the middleware level — no route-level auth
dependency needed.

R9: reads only from ``intelligence_db`` (S7's own DB).
R25: API → use case only.
R27: uses ``ReadOnlyDbSessionDep``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from knowledge_graph.api.dependencies import ReadOnlyDbSessionDep
from knowledge_graph.application.use_cases.intelligence_rollup import (
    GetIntelligenceRollup7dUseCase,
)

router = APIRouter(prefix="/internal/v1", tags=["internal", "rollup"])


class IntelligenceRollup7dResponse(BaseModel):
    """Response body for the 7d intelligence rollup endpoint."""

    instrument_id: UUID
    recent_contradiction_count: int = Field(
        ge=0,
        description="Count of active contradictions where the entity is the subject, in the last 7 days.",
    )


@router.get(
    "/instruments/{instrument_id}/intelligence-rollup-7d",
    response_model=IntelligenceRollup7dResponse,
    summary="[Internal] 7-day intelligence rollup (contradiction count) for screener sync",
)
async def get_intelligence_rollup_7d(
    instrument_id: UUID,
    session: ReadOnlyDbSessionDep,
) -> IntelligenceRollup7dResponse:
    """Return a small intelligence rollup for ``instrument_id``.

    The endpoint is non-failing: if the instrument has no canonical entity
    or no contradictions, ``recent_contradiction_count`` is ``0`` and the
    HTTP status is still ``200``. This matches the L-5b nightly sync
    contract (the worker treats a row as "no signal" rather than retrying).
    """
    result = await GetIntelligenceRollup7dUseCase().execute(
        session=session,
        instrument_id=instrument_id,
    )
    return IntelligenceRollup7dResponse(
        instrument_id=instrument_id,
        recent_contradiction_count=result.recent_contradiction_count,
    )
