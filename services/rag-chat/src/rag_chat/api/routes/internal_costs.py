"""GET /internal/v1/llm-costs — per-period LLM cost summary for rag-chat.

PLAN-0033 T-E-2-01.

Auth: ``X-Internal-JWT`` required; enforced by ``InternalJWTMiddleware``.
R25: imports only from ``application/use_cases/``.
R27: uses read-only session via ``get_rag_read_session`` (read replica factory).
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from rag_chat.application.use_cases.get_llm_costs import (
    ALLOWED_BREAKDOWNS,
    ALLOWED_PROVIDERS,
    GetRagLlmCostsUseCase,
)

router = APIRouter(prefix="/internal/v1", tags=["internal"])

_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


# ── Session dependency ────────────────────────────────────────────────────────


async def get_rag_read_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a read-only AsyncSession from the read replica factory (R27)."""
    async with request.app.state.read_factory() as session:
        yield session


RagReadDbSessionDep = Annotated[AsyncSession, Depends(get_rag_read_session)]


# ── Response schemas ──────────────────────────────────────────────────────────


class CostBreakdownItemSchema(BaseModel):
    dimension: str
    calls: int
    tokens_in: int
    tokens_out: int
    estimated_cost_usd: float
    success_rate: float


class LlmCostsResponse(BaseModel):
    service: str
    period: str
    total_estimated_cost_usd: float
    total_calls: int
    total_tokens_in: int
    total_tokens_out: int
    success_rate: float
    breakdown: list[CostBreakdownItemSchema]


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get("/llm-costs", response_model=LlmCostsResponse)
async def get_llm_costs(
    session: RagReadDbSessionDep,
    period: str | None = Query(default=None),
    provider: str = Query(default="all"),
    breakdown: str = Query(default="provider"),
) -> LlmCostsResponse:
    """Return aggregated LLM cost and token usage for rag-chat.

    Queries rag_chat_db.llm_usage_log (no service_name filter — this DB is
    owned exclusively by S8).
    """
    if period is None:
        now = datetime.now(tz=UTC)
        period = f"{now.year:04d}-{now.month:02d}"

    if not _PERIOD_RE.match(period):
        raise HTTPException(status_code=400, detail="period must be YYYY-MM format")

    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"provider must be one of: {', '.join(sorted(ALLOWED_PROVIDERS))}",
        )
    if breakdown not in ALLOWED_BREAKDOWNS:
        raise HTTPException(
            status_code=400,
            detail=f"breakdown must be one of: {', '.join(sorted(ALLOWED_BREAKDOWNS))}",
        )

    result = await GetRagLlmCostsUseCase().execute(session, period=period, provider=provider, breakdown=breakdown)

    return LlmCostsResponse(
        service=result.service,
        period=result.period,
        total_estimated_cost_usd=result.total_estimated_cost_usd,
        total_calls=result.total_calls,
        total_tokens_in=result.total_tokens_in,
        total_tokens_out=result.total_tokens_out,
        success_rate=result.success_rate,
        breakdown=[
            CostBreakdownItemSchema(
                dimension=item.dimension,
                calls=item.calls,
                tokens_in=item.tokens_in,
                tokens_out=item.tokens_out,
                estimated_cost_usd=item.estimated_cost_usd,
                success_rate=item.success_rate,
            )
            for item in result.breakdown
        ],
    )
