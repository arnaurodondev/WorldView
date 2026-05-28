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
R27: uses a read-only session via ``ReadUoWDep``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from rag_chat.application.use_cases.ai_brief_flag import GetAiBriefFlagUseCase

router = APIRouter(prefix="/internal/v1", tags=["internal", "rollup"])


# WHY a dedicated read session dep (not ReadUoWDep): the use case needs a raw
# AsyncSession to run a small COUNT/MAX query; RagUnitOfWork wires repos for
# threads/messages but does not expose .session. This mirrors the pattern in
# ``get_brief_archive_dep`` (api/dependencies.py:71-98) which also reaches
# into ``read_factory`` directly for a read-only repository.
async def _get_read_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session = request.app.state.read_factory()
    try:
        yield session
    finally:
        await session.close()


ReadSessionDep = Annotated[AsyncSession, Depends(_get_read_session)]


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
    session: ReadSessionDep,
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
