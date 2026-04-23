"""GET /api/v1/admin/llm-costs — cross-service LLM cost aggregation (PLAN-0033 T-F-1-01).

Requires admin role (role == "admin" in request.state.user).
Fan-out to S6/S7/S8 internal endpoints via asyncio.gather; returns partial results
on service failures — 200 when at least one service responds, 503 when all fail.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

_TIMEOUT = 5.0  # seconds per downstream call


# ── Response schemas ──────────────────────────────────────────────────────────


class CostBreakdownItemSchema(BaseModel):
    dimension: str
    calls: int
    tokens_in: int
    tokens_out: int
    estimated_cost_usd: float
    success_rate: float


class ServiceCostSummary(BaseModel):
    service: str
    period: str
    total_estimated_cost_usd: float
    total_calls: int
    total_tokens_in: int
    total_tokens_out: int
    success_rate: float
    breakdown: list[CostBreakdownItemSchema]
    error: str | None = None  # set when upstream call failed


class AdminLlmCostsResponse(BaseModel):
    period: str
    services: list[ServiceCostSummary]
    grand_total_estimated_cost_usd: float
    grand_total_calls: int


# ── Auth helper ───────────────────────────────────────────────────────────────


def _require_admin(request: Request) -> None:
    """Raise 403 if the authenticated user does not have admin role."""
    user: dict[str, Any] | None = getattr(request.state, "user", None)
    if user is None or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")


# ── Downstream call ───────────────────────────────────────────────────────────


async def _fetch_service_costs(
    client: Any,
    service_name: str,
    period: str,
    provider: str,
    breakdown: str,
    internal_jwt: str,
) -> ServiceCostSummary:
    """Call one service's /internal/v1/llm-costs and return a summary."""
    try:
        resp = await asyncio.wait_for(
            client.get(
                "/internal/v1/llm-costs",
                params={"period": period, "provider": provider, "breakdown": breakdown},
                headers={"X-Internal-JWT": internal_jwt},
            ),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return ServiceCostSummary(
            service=data["service"],
            period=data["period"],
            total_estimated_cost_usd=data["total_estimated_cost_usd"],
            total_calls=data["total_calls"],
            total_tokens_in=data["total_tokens_in"],
            total_tokens_out=data["total_tokens_out"],
            success_rate=data["success_rate"],
            breakdown=[CostBreakdownItemSchema(**item) for item in data.get("breakdown", [])],
        )
    except Exception as exc:
        # Return a stub summary with error info — partial success still returns 200
        return ServiceCostSummary(
            service=service_name,
            period=period,
            total_estimated_cost_usd=0.0,
            total_calls=0,
            total_tokens_in=0,
            total_tokens_out=0,
            success_rate=0.0,
            breakdown=[],
            error=str(exc)[:200],
        )


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get("/llm-costs", response_model=AdminLlmCostsResponse)
async def get_admin_llm_costs(
    request: Request,
    period: str | None = Query(default=None),
    provider: str = Query(default="all"),
    breakdown: str = Query(default="provider"),
) -> AdminLlmCostsResponse:
    """Aggregate LLM costs across S6 (nlp-pipeline), S7 (knowledge-graph), S8 (rag-chat).

    Returns partial results if one or two services are unavailable.
    Returns 503 only when ALL three services fail.
    """
    _require_admin(request)

    # Default period to current UTC month
    if period is None:
        from datetime import UTC, datetime

        now = datetime.now(tz=UTC)
        period = f"{now.year:04d}-{now.month:02d}"

    # Validate period format: YYYY-MM
    if not _PERIOD_RE.match(period):
        raise HTTPException(status_code=400, detail="period must be in YYYY-MM format")

    # Extract the internal JWT that S9's InternalJWTIssuerMiddleware already injected
    # into the request scope headers (mutates request.scope["headers"] before calling
    # call_next — so request.headers reflects the updated value by the time this handler runs).
    internal_jwt: str = request.headers.get("x-internal-jwt", "")

    clients = request.app.state.clients

    # Fan-out to all three services concurrently
    results = await asyncio.gather(
        _fetch_service_costs(clients.nlp_pipeline, "nlp-pipeline", period, provider, breakdown, internal_jwt),
        _fetch_service_costs(clients.knowledge_graph, "knowledge-graph", period, provider, breakdown, internal_jwt),
        _fetch_service_costs(clients.rag_chat, "rag-chat", period, provider, breakdown, internal_jwt),
        return_exceptions=False,  # exceptions are caught inside _fetch_service_costs
    )

    services = list(results)

    # 503 only if ALL services failed
    if all(s.error is not None for s in services):
        raise HTTPException(status_code=503, detail="All LLM cost services unavailable")

    grand_total_cost = sum(s.total_estimated_cost_usd for s in services)
    grand_total_calls = sum(s.total_calls for s in services)

    return AdminLlmCostsResponse(
        period=period,
        services=services,
        grand_total_estimated_cost_usd=grand_total_cost,
        grand_total_calls=grand_total_calls,
    )
