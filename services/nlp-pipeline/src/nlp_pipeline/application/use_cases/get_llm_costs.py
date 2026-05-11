"""Read-only use case for GET /internal/v1/llm-costs (PLAN-0033 T-C-3-01).

Queries nlp_db.llm_usage_log and returns per-period cost aggregates grouped by
the requested dimension (provider / capability / day).

R25 compliance: only the route file imports this; the route file imports no
infrastructure layer code directly.
R27 compliance: the route passes a read-only session obtained from the read
replica session factory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ── Validation constants (imported by route for query-param validation) ───────

ALLOWED_PROVIDERS: frozenset[str] = frozenset({"all", "deepinfra", "openrouter", "gemini", "ollama"})
ALLOWED_BREAKDOWNS: frozenset[str] = frozenset({"provider", "capability", "day"})


# ── Result value objects ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class CostBreakdownItem:
    """One row in the aggregated breakdown result."""

    dimension: str
    calls: int
    tokens_in: int
    tokens_out: int
    estimated_cost_usd: float
    success_rate: float


@dataclass(frozen=True)
class LlmCostsResult:
    """Full aggregated result returned by GetNlpLlmCostsUseCase.execute()."""

    service: str
    period: str
    total_estimated_cost_usd: float
    total_calls: int
    total_tokens_in: int
    total_tokens_out: int
    success_rate: float
    breakdown: list[CostBreakdownItem] = field(default_factory=list)


# ── Pre-built SQL queries per breakdown dimension (no f-string injection) ─────
# Each query is a static string to avoid S608 linter warnings.
# They use named bind params :period_date and :provider.

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


class GetNlpLlmCostsUseCase:
    """Aggregate LLM usage log rows from nlp_db for the requested period."""

    async def execute(
        self,
        session: AsyncSession,
        period: str,
        provider: str = "all",
        breakdown: str = "provider",
    ) -> LlmCostsResult:
        """Return aggregated cost breakdown from nlp_db.llm_usage_log.

        Args:
            session:   Read-only SQLAlchemy AsyncSession (from read replica).
            period:    YYYY-MM string (validated by route before this call).
            provider:  Provider filter; 'all' disables the filter.
            breakdown: Aggregation dimension ('provider', 'capability', 'day').
        """
        from sqlalchemy import text

        sql = _BREAKDOWN_QUERIES[breakdown]  # safe: caller validates against ALLOWED_BREAKDOWNS
        result = await session.execute(
            text(sql),
            {"period_date": date.fromisoformat(f"{period}-01"), "provider": provider},
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
            service="nlp-pipeline",
            period=period,
            total_estimated_cost_usd=total_cost,
            total_calls=total_calls,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            success_rate=avg_success,
            breakdown=items,
        )
