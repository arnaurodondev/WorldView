"""POST /internal/v1/llm-usage — internal LLM-usage ingest (PLAN-0117 W4, FR-6).

The S9 api-gateway makes a direct DeepInfra call for the screener NL→filter
translation and owns no cost ledger (R9). It POSTs the usage record here so the
spend lands in the single S8 ``rag_db.llm_usage_log``.

Auth: internal-only. ``X-Internal-JWT`` is required — enforced by
``InternalJWTMiddleware`` + ``AuthContextDep`` (a missing/invalid token yields
401 before the body is persisted). This mirrors the sibling internal routes
(``internal_costs.py`` — ``APIRouter(prefix="/internal/v1")``).

Best-effort (NFR-1): the endpoint returns ``200 {"recorded": true|false}`` — it
NEVER 500s on a persistence failure, so the gateway's best-effort caller can
fire-and-forget without any risk of failing the user's screener request.

R25: the router depends only on the application-layer ``RecordLlmUsageUseCase``.
R27: writes use the write-engine session factory (``app.state.write_factory``).
BP-064: 200 + dict, never 204.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from rag_chat.api.dependencies import AuthContextDep
from rag_chat.application.use_cases.record_llm_usage import RecordLlmUsageUseCase

router = APIRouter(prefix="/internal/v1", tags=["internal"])
log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


# ── Write session dependency (R27) ────────────────────────────────────────────


async def get_rag_write_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a write-capable AsyncSession from the write engine factory (R27)."""
    session = request.app.state.write_factory()
    try:
        yield session
    finally:
        await session.close()


RagWriteDbSessionDep = Annotated[AsyncSession, Depends(get_rag_write_session)]


# ── Request / response schemas ────────────────────────────────────────────────


class LlmUsageIngestRequest(BaseModel):
    """One LLM usage record to persist into rag_db.llm_usage_log (PRD-0117 §6.2)."""

    model_id: str = Field(..., min_length=1, max_length=200)
    provider: str = Field(..., min_length=1, max_length=50)
    capability: str = Field(..., min_length=1, max_length=50)
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    estimated_cost_usd: Decimal = Field(..., ge=0)
    cost_source: str = Field(..., min_length=1, max_length=16)
    latency_ms: int = Field(default=0, ge=0)
    success: bool = Field(default=True)
    error_code: str | None = Field(default=None, max_length=50)
    tenant_id: UUID | None = Field(default=None)
    user_id: UUID | None = Field(default=None)


class LlmUsageIngestResponse(BaseModel):
    """Best-effort ack: ``recorded`` is False when persistence failed (NFR-1)."""

    recorded: bool


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post("/llm-usage", status_code=200, response_model=LlmUsageIngestResponse)
async def ingest_llm_usage(
    body: LlmUsageIngestRequest,
    session: RagWriteDbSessionDep,
    auth: AuthContextDep,
) -> LlmUsageIngestResponse:
    """Persist a caller-supplied LLM usage record (internal-only, best-effort).

    ``auth`` enforces the internal JWT (401 when absent/invalid). The record's
    ``tenant_id``/``user_id`` come from the body (the gateway fills them from its
    own auth context); when the body omits them we fall back to the JWT identity
    so the row is never orphaned from its caller.
    """
    jwt_tenant_id, jwt_user_id = auth
    uc = RecordLlmUsageUseCase()
    recorded = await uc.execute(
        session,
        model_id=body.model_id,
        provider=body.provider,
        capability=body.capability,
        tokens_in=body.tokens_in,
        tokens_out=body.tokens_out,
        estimated_cost_usd=body.estimated_cost_usd,
        cost_source=body.cost_source,
        latency_ms=body.latency_ms,
        success=body.success,
        error_code=body.error_code,
        tenant_id=body.tenant_id or jwt_tenant_id,
        user_id=body.user_id or jwt_user_id,
    )
    return LlmUsageIngestResponse(recorded=recorded)
