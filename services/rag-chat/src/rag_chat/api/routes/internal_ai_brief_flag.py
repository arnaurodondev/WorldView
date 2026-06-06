"""GET /internal/v1/instruments/{instrument_id}/ai-brief-flag.

PLAN-0089 Wave L-5a (T-WL5A-03) — read-only rollup consumed by the S3-side
screener sync worker (Wave L-5b) to materialise the
``instrument_intelligence_snapshot.has_ai_brief`` +
``ai_brief_generated_at`` columns.

Auth: ``X-Internal-JWT`` header required; enforced by
``InternalJWTMiddleware`` at the middleware level — no route-level auth
dependency needed.

R9: reads only from ``rag_chat_db`` (S8's own DB).
R25: API → use case only.
R27: uses the canonical ``ReadOnlyDbSessionDep`` (raw read-only AsyncSession),
mirroring ``knowledge_graph.api.internal_intelligence_rollup``. Fix for
WL-5a QA finding #3 — replaces a previously inlined ``_get_read_session``
helper to remove the micro-divergence from the platform standard.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from rag_chat.api.dependencies import ReadOnlyDbSessionDep
from rag_chat.application.use_cases.ai_brief_flag import GetAiBriefFlagUseCase

router = APIRouter(prefix="/internal/v1", tags=["internal", "rollup"])


class AiBriefFlagResponse(BaseModel):
    """Response body for the AI-brief-flag endpoint."""

    instrument_id: UUID
    has_ai_brief: bool
    brief_generated_at: datetime | None = None


@router.get(
    "/instruments/{instrument_id}/ai-brief-flag",
    response_model=AiBriefFlagResponse,
)
async def get_ai_brief_flag(
    instrument_id: UUID,
    session: ReadOnlyDbSessionDep,
) -> AiBriefFlagResponse:
    """Return whether any cached entity-scoped AI brief exists for ``instrument_id``.

    Endpoint is non-failing: instruments with no entity brief return
    ``has_ai_brief=False`` + ``brief_generated_at=null`` with HTTP 200.
    The L-5b nightly sync worker treats absence as "no signal" and does
    not retry.
    """
    flag = await GetAiBriefFlagUseCase().execute(session=session, instrument_id=instrument_id)
    return AiBriefFlagResponse(
        instrument_id=instrument_id,
        has_ai_brief=flag.has_ai_brief,
        brief_generated_at=flag.brief_generated_at,
    )
