"""LLM usage log repository (PRD §6.7 Block E2 — cost visibility).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

Every LLM call (embedding or extraction) must be logged here,
including Ollama calls at $0 estimated cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class LlmUsageLogRepository:
    """Append-only repository for ``llm_usage_log``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(
        self,
        model_id: str,
        provider: str,
        capability: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        *,
        entity_id: UUID | None = None,
        relation_id: UUID | None = None,
        estimated_cost_usd: float = 0.0,
        success: bool = True,
    ) -> UUID:
        """Append a usage log row and return log_id.

        Args:
            model_id:  Model identifier (e.g. "ollama/nomic-embed-text").
            provider:  Provider name (e.g. "ollama", "gemini").
            capability: "embedding" or "extraction".
            tokens_in:  Input token count.
            tokens_out: Output token count.
            latency_ms: Wall-clock latency in milliseconds.
            entity_id:  Optional entity being processed.
            relation_id: Optional relation being processed.
            estimated_cost_usd: Estimated cost (0.0 for Ollama).
            success:    Whether the call succeeded.
        """
        result = await self._session.execute(
            text("""
INSERT INTO llm_usage_log (
    model_id, provider, capability,
    entity_id, relation_id,
    tokens_in, tokens_out, estimated_cost_usd,
    latency_ms, success
) VALUES (
    :model_id, :provider, :capability,
    :entity_id, :relation_id,
    :tokens_in, :tokens_out, :estimated_cost_usd,
    :latency_ms, :success
)
RETURNING log_id
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
            },
        )
        row = result.fetchone()
        return UUID(str(row[0]))  # type: ignore[index]
