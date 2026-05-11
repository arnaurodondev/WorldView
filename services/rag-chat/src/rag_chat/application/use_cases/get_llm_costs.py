"""Read-only use case for GET /internal/v1/llm-costs (PLAN-0033 T-E-2-01).

Queries rag_chat_db.llm_usage_log (owned exclusively by S8 — no service_name
filter needed) and returns per-period cost aggregates.

R25 compliance: only the route file imports this class.
R27 compliance: caller passes a read-only session from the read replica.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ── Validation constants ──────────────────────────────────────────────────────

ALLOWED_PROVIDERS: frozenset[str] = frozenset({"all", "deepinfra", "openrouter", "gemini", "ollama"})
ALLOWED_BREAKDOWNS: frozenset[str] = frozenset({"provider", "capability", "day"})


# ── Result value objects ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class CostBreakdownItem:
    dimension: str
    calls: int
    tokens_in: int
    tokens_out: int
    estimated_cost_usd: float
    success_rate: float


@dataclass(frozen=True)
class LlmCostsResult:
    service: str
    period: str
    total_estimated_cost_usd: float
    total_calls: int
    total_tokens_in: int
    total_tokens_out: int
    success_rate: float
    breakdown: list[CostBreakdownItem] = field(default_factory=list)


# ── Pre-built SQL queries (rag_chat_db, no service_name filter) ───────────────

_PROVIDER_QUERY = """
    SELECT
        provider AS dimension,
        COUNT(*) AS calls,
        SUM(tokens_in) AS tokens_in,
        SUM(tokens_out) AS tokens_out,
        SUM(estimated_cost_usd) AS estimated_cost_usd,
        AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) AS success_rate
    FROM llm_usage_log
    WHERE DATE_TRUNC('month', created_at AT TIME ZONE 'UTC')
          = DATE_TRUNC('month', CAST(:period_date AS DATE))
      AND (:provider = 'all' OR provider = :provider)
    GROUP BY provider
    ORDER BY estimated_cost_usd DESC
"""

_CAPABILITY_QUERY = """
    SELECT
        capability AS dimension,
        COUNT(*) AS calls,
        SUM(tokens_in) AS tokens_in,
        SUM(tokens_out) AS tokens_out,
        SUM(estimated_cost_usd) AS estimated_cost_usd,
        AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) AS success_rate
    FROM llm_usage_log
    WHERE DATE_TRUNC('month', created_at AT TIME ZONE 'UTC')
          = DATE_TRUNC('month', CAST(:period_date AS DATE))
      AND (:provider = 'all' OR provider = :provider)
    GROUP BY capability
    ORDER BY estimated_cost_usd DESC
"""

_DAY_QUERY = """
    SELECT
        CAST(created_at AT TIME ZONE 'UTC' AS DATE)::text AS dimension,
        COUNT(*) AS calls,
        SUM(tokens_in) AS tokens_in,
        SUM(tokens_out) AS tokens_out,
        SUM(estimated_cost_usd) AS estimated_cost_usd,
        AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) AS success_rate
    FROM llm_usage_log
    WHERE DATE_TRUNC('month', created_at AT TIME ZONE 'UTC')
          = DATE_TRUNC('month', CAST(:period_date AS DATE))
      AND (:provider = 'all' OR provider = :provider)
    GROUP BY 1
    ORDER BY dimension ASC
"""

_BREAKDOWN_QUERIES: dict[str, str] = {
    "provider": _PROVIDER_QUERY,
    "capability": _CAPABILITY_QUERY,
    "day": _DAY_QUERY,
}


# ── Use case ──────────────────────────────────────────────────────────────────


class GetRagLlmCostsUseCase:
    """Aggregate LLM usage rows from rag_chat_db for the rag-chat service."""

    async def execute(
        self,
        session: AsyncSession,
        period: str,
        provider: str = "all",
        breakdown: str = "provider",
    ) -> LlmCostsResult:
        from sqlalchemy import text

        sql = _BREAKDOWN_QUERIES[breakdown]  # safe: validated in route before call
        result = await session.execute(
            text(sql),
            {"period_date": f"{period}-01", "provider": provider},
        )
        rows = result.fetchall()

        items = [
            CostBreakdownItem(
                dimension=str(row.dimension or ""),
                calls=int(row.calls or 0),
                tokens_in=int(row.tokens_in or 0),
                tokens_out=int(row.tokens_out or 0),
                estimated_cost_usd=float(row.estimated_cost_usd or 0.0),
                success_rate=float(row.success_rate or 1.0),
            )
            for row in rows
        ]

        total_calls = sum(i.calls for i in items)
        total_tokens_in = sum(i.tokens_in for i in items)
        total_tokens_out = sum(i.tokens_out for i in items)
        total_cost = sum(i.estimated_cost_usd for i in items)
        avg_success = sum(i.success_rate * i.calls for i in items) / total_calls if total_calls > 0 else 1.0

        return LlmCostsResult(
            service="rag-chat",
            period=period,
            total_estimated_cost_usd=total_cost,
            total_calls=total_calls,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            success_rate=avg_success,
            breakdown=items,
        )
