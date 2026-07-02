"""LLM usage log repository for rag_chat_db (PLAN-0033 T-E-1-01).

Satisfies ``LlmUsageLogProtocol`` — writes to rag_chat_db.llm_usage_log.
Fire-and-forget observer: ALL internal exceptions are swallowed so that a
cost-logging failure NEVER disrupts the chat streaming path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class RagChatUsageLogRepository:
    """Append-only cost-log repository for rag_chat_db.llm_usage_log.

    Implements ``LlmUsageLogProtocol`` structurally — no explicit inheritance
    needed because the protocol is ``@runtime_checkable``.

    Service-specific **context** kwargs understood:
      session_id      — UUID of the RAG session when the call was made
      chat_thread_id  — UUID of the chat thread
      tenant_id       — UUID of the tenant (optional)
      cost_source     — provenance of ``estimated_cost_usd`` (PLAN-0117 FR-2):
                        ``provider`` | ``pricematrix`` | ``local`` | ``aggregate``
                        (NULL for legacy/pre-0117 callers). ``aggregate`` marks a
                        wrapper row that duplicates a leaf's tokens at $0 so the
                        FR-7 silent-zero guard can exempt it (no double count).
      user_id         — UUID of the authenticated end user (PLAN-0117 FR-3);
                        NULL for system/background calls.
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

            session_id = context.get("session_id")
            chat_thread_id = context.get("chat_thread_id")
            tenant_id = context.get("tenant_id")
            # PLAN-0117 W4 (FR-2/FR-3): provenance + authenticated user. Both are
            # optional context kwargs so every legacy call site keeps compiling;
            # they resolve to NULL when omitted (pre-0117 semantics).
            cost_source = context.get("cost_source")
            user_id = context.get("user_id")

            await self._session.execute(
                text(
                    """
                    INSERT INTO llm_usage_log (
                        log_id,
                        model_id, provider, capability,
                        service_name, tenant_id,
                        tokens_in, tokens_out, estimated_cost_usd,
                        latency_ms, success, error_code,
                        session_id, chat_thread_id,
                        cost_source, user_id
                    ) VALUES (
                        :log_id,
                        :model_id, :provider, :capability,
                        'rag-chat', :tenant_id,
                        :tokens_in, :tokens_out, :estimated_cost_usd,
                        :latency_ms, :success, :error_code,
                        :session_id, :chat_thread_id,
                        :cost_source, :user_id
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
                    "session_id": str(session_id) if session_id is not None else None,
                    "chat_thread_id": str(chat_thread_id) if chat_thread_id is not None else None,
                    "cost_source": str(cost_source) if cost_source is not None else None,
                    "user_id": str(user_id) if user_id is not None else None,
                },
            )
        except Exception as exc:
            logger.warning("rag_usage_log_failed", error=str(exc))
