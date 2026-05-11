"""GET /internal/v1/llm-costs — per-period LLM cost summary for nlp-pipeline.

PLAN-0033 T-C-3-01.

Auth: ``X-Internal-JWT`` header required; enforced by ``InternalJWTMiddleware``
at the middleware level — no route-level auth dependency needed.

R25 compliance: this file imports only from ``application/use_cases/``.
R27 compliance: uses the read-replica session factory via NlpReadDbSessionDep.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nlp_pipeline.application.use_cases.get_llm_costs import (
    ALLOWED_BREAKDOWNS,
    ALLOWED_PROVIDERS,
    GetNlpLlmCostsUseCase,
)

router = APIRouter(prefix="/internal/v1", tags=["internal"])

_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


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


# ── Read-only session dependency (R27) ────────────────────────────────────────


async def get_nlp_read_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a read-only AsyncSession from the nlp_read_factory (read replica)."""
    async with request.app.state.nlp_read_factory() as session:
        yield session


NlpReadDbSessionDep = Annotated[AsyncSession, Depends(get_nlp_read_session)]


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get("/llm-costs", response_model=LlmCostsResponse)
async def get_llm_costs(
    session: NlpReadDbSessionDep,
    period: str | None = Query(
        default=None,
        description="Billing period in YYYY-MM format. Defaults to the current UTC month.",
    ),
    provider: str = Query(default="all", description="Provider filter; 'all' returns all providers."),
    breakdown: str = Query(default="provider", description="Aggregation dimension."),
) -> LlmCostsResponse:
    """Return aggregated LLM cost and token usage for nlp-pipeline.

    Query params:
    - ``period``: YYYY-MM (default: current UTC month).
    - ``provider``: ``all | deepinfra | openrouter | gemini | ollama``.
    - ``breakdown``: ``provider | capability | day``.

    Returns 400 on invalid period format or unknown provider/breakdown value.
    """
    # Default period to current UTC month
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

    result = await GetNlpLlmCostsUseCase().execute(session, period=period, provider=provider, breakdown=breakdown)

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
