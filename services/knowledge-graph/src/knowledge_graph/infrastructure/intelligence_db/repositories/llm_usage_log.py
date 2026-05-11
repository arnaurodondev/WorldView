"""LLM usage log repository (PRD §6.7 Block E2 — cost visibility).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

Every LLM call (embedding or extraction) must be logged here,
including Ollama calls at $0 estimated cost.

PLAN-0033 T-D-1-02:
  - Renamed ``insert()`` → ``log()`` to satisfy ``LlmUsageLogProtocol``
  - Added ``**context`` kwargs for entity_id, relation_id, tenant_id
  - INSERT now includes service_name, tenant_id, error_code (migration 0006)
  - Return type changed from UUID to None (protocol requires None)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class LlmUsageLogRepository:
    """Append-only repository for ``intelligence_db.llm_usage_log``.

    Implements ``LlmUsageLogProtocol`` structurally.

    Service-specific **context** kwargs understood:
      entity_id   — UUID of entity being processed
      relation_id — UUID of relation being processed
      tenant_id   — UUID for multi-tenant tracking
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        *,
        model_id: str,
        provider: str,
        capability: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        estimated_cost_usd: float = 0.0,
        success: bool = True,
        error_code: str | None = None,
        **context: object,
    ) -> None:
        """Append a usage log row.

        All exceptions are swallowed — this method must never propagate
        an error to the caller (cost logging is a non-critical observer).

        Args:
        ----
            model_id:            Model identifier (e.g. "ollama/nomic-embed-text").
            provider:            Provider name (e.g. "ollama", "gemini").
            capability:          "embedding" or "extraction".
            tokens_in:           Input token count.
            tokens_out:          Output token count.
            latency_ms:          Wall-clock latency in milliseconds.
            estimated_cost_usd:  Estimated cost (0.0 for Ollama).
            success:             Whether the call succeeded.
            error_code:          Short error tag (None on success).
            **context:           entity_id, relation_id, tenant_id (all optional).

        """
        try:
            entity_id = context.get("entity_id")
            relation_id = context.get("relation_id")
            tenant_id = context.get("tenant_id")

            await self._session.execute(
                text("""
INSERT INTO llm_usage_log (
    model_id, provider, capability,
    entity_id, relation_id,
    tokens_in, tokens_out, estimated_cost_usd,
    latency_ms, success,
    service_name, tenant_id, error_code
) VALUES (
    :model_id, :provider, :capability,
    :entity_id, :relation_id,
    :tokens_in, :tokens_out, :estimated_cost_usd,
    :latency_ms, :success,
    'knowledge-graph', :tenant_id, :error_code
)
"""),
                {
                    "model_id": model_id,
                    "provider": provider,
                    "capability": capability,
                    "entity_id": str(entity_id) if entity_id else None,
                    "relation_id": str(relation_id) if relation_id else None,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "estimated_cost_usd": estimated_cost_usd,
                    "latency_ms": latency_ms,
                    "success": success,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "error_code": error_code,
                },
            )
        except Exception as exc:
            logger.warning("kg_usage_log_failed", error=str(exc))
