"""LLM usage log repository for nlp_db (PLAN-0033 T-C-1-03).

Satisfies ``LlmUsageLogProtocol`` — writes to nlp_db.llm_usage_log.
Designed to be a fire-and-forget observer: ALL internal exceptions are swallowed
so that a cost-logging failure NEVER disrupts the main processing path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class NlpUsageLogRepository:
    """Append-only cost-log repository for nlp_db.llm_usage_log.

    Implements ``LlmUsageLogProtocol`` structurally — no explicit inheritance
    needed because the protocol is ``@runtime_checkable``.

    Service-specific **context** kwargs understood:
      doc_id    — UUID of the document being processed when the call was made
      tenant_id — UUID of the tenant (optional, for future multi-tenancy)
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
        """Insert one usage log row.

        All exceptions are caught and logged as warnings — this method
        must never raise regardless of DB state.
        """
        try:
            from sqlalchemy import text

            from common.ids import new_uuid7  # type: ignore[import-untyped]

            doc_id = context.get("doc_id")
            tenant_id = context.get("tenant_id")
            # Task #36: optional resilience-audit tag. ``model_id`` above already
            # carries the ACTUAL serving model (the caller passes ExtractionOutput
            # .model_used). ``fallback_reason`` records WHY a fallback fired:
            # none | rate_limit | timeout | server_error. NULL for non-extraction
            # callers that don't pass it (the column is nullable). We coerce to a
            # str|None so a stray non-string in **context never breaks the INSERT.
            fallback_reason = context.get("fallback_reason")
            fallback_reason_str = str(fallback_reason) if fallback_reason is not None else None

            await self._session.execute(
                text(
                    """
                    INSERT INTO llm_usage_log (
                        log_id,
                        model_id, provider, capability,
                        service_name, tenant_id,
                        tokens_in, tokens_out, estimated_cost_usd,
                        latency_ms, success, error_code, doc_id,
                        fallback_reason
                    ) VALUES (
                        :log_id,
                        :model_id, :provider, :capability,
                        'nlp-pipeline', :tenant_id,
                        :tokens_in, :tokens_out, :estimated_cost_usd,
                        :latency_ms, :success, :error_code, :doc_id,
                        :fallback_reason
                    )
                    """,
                ),
                {
                    "log_id": str(new_uuid7()),
                    "model_id": model_id,
                    "provider": provider,
                    "capability": capability,
                    "tenant_id": str(tenant_id) if tenant_id is not None else None,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "estimated_cost_usd": estimated_cost_usd,
                    "latency_ms": latency_ms,
                    "success": success,
                    "error_code": error_code,
                    "doc_id": str(doc_id) if doc_id is not None else None,
                    "fallback_reason": fallback_reason_str,
                },
            )
        except Exception as exc:
            # Observer must never affect subject — swallow all DB errors
            logger.warning("nlp_usage_log_failed", error=str(exc))
