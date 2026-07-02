"""Record one externally-supplied LLM usage record (PLAN-0117 W4, FR-6).

The S9 api-gateway makes a **direct** DeepInfra call for the screener
NL→filter translation (``POST /v1/screener/nl-translate``). The gateway owns
no ``llm_usage_log`` DB (R9 — it must not grow one), so it POSTs the usage
record to this use case via the internal S8 route ``POST /internal/v1/llm-usage``.
The record is persisted into ``rag_db.llm_usage_log`` so ALL gateway-adjacent
LLM spend lands in the single S8 ledger.

R25 / LAYER-APP-ISOLATION: the use case runs the INSERT with a raw ``text()``
statement on the caller-supplied session (mirroring the sibling
``GetRagLlmCostsUseCase``) — it imports NO infrastructure module. The router
passes a write session (R27); the application layer stays infra-free.

NFR-1 (best-effort): ``execute`` never raises. It returns ``True`` when the row
was committed and ``False`` on any persistence error, so the internal route can
answer ``200 {"recorded": <bool>}`` and the gateway's best-effort caller never
sees a 5xx purely because logging failed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from decimal import Decimal
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Column set mirrors rag_db.llm_usage_log (see rag-chat migration 0010 for the
# cost_source + user_id additions). ``service_name`` is fixed to 'rag-chat'
# because this DB is owned exclusively by S8.
_INSERT_SQL = """
    INSERT INTO llm_usage_log (
        log_id,
        model_id, provider, capability,
        service_name, tenant_id,
        tokens_in, tokens_out, estimated_cost_usd,
        latency_ms, success, error_code,
        cost_source, user_id
    ) VALUES (
        :log_id,
        :model_id, :provider, :capability,
        'rag-chat', :tenant_id,
        :tokens_in, :tokens_out, :estimated_cost_usd,
        :latency_ms, :success, :error_code,
        :cost_source, :user_id
    )
"""


class RecordLlmUsageUseCase:
    """Persist a single caller-supplied LLM usage record into rag_db."""

    async def execute(
        self,
        session: AsyncSession,
        *,
        model_id: str,
        provider: str,
        capability: str,
        tokens_in: int,
        tokens_out: int,
        estimated_cost_usd: Decimal,
        cost_source: str,
        latency_ms: int = 0,
        success: bool = True,
        error_code: str | None = None,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> bool:
        """Write one usage row. Returns True on commit, False on any failure.

        Never raises — a logging-ingest failure must not surface to the caller
        (NFR-1). The row is committed in its own short transaction.
        """
        try:
            from sqlalchemy import text

            from common.ids import new_uuid7  # type: ignore[import-untyped]

            await session.execute(
                text(_INSERT_SQL),
                {
                    "log_id": str(new_uuid7()),
                    "model_id": model_id,
                    "provider": provider,
                    "capability": capability,
                    "tenant_id": str(tenant_id) if tenant_id is not None else None,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    # DOUBLE PRECISION column; float() at the boundary is lossless
                    # enough for a per-call cost snapshot (the Decimal was resolved
                    # upstream and stays exact in the caller's record).
                    "estimated_cost_usd": float(estimated_cost_usd),
                    "latency_ms": latency_ms,
                    "success": success,
                    "error_code": error_code,
                    "cost_source": cost_source,
                    "user_id": str(user_id) if user_id is not None else None,
                },
            )
            await session.commit()
        except Exception as exc:
            log.warning(
                "record_llm_usage_failed",
                capability=capability,
                model_id=model_id,
                error=str(exc),
            )
            return False
        return True


__all__ = ["RecordLlmUsageUseCase"]
