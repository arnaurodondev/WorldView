"""Session-scoped RAG usage logger (PLAN-0052 QA-R6).

Mirrors nlp_pipeline.infrastructure.nlp_db.usage_log_factory.SessionScopedNlpUsageLogger
but writes to rag_chat_db.llm_usage_log (the rag-chat local cost ledger).

Why session-scoped?
~~~~~~~~~~~~~~~~~~~
``RagChatUsageLogRepository`` needs an open ``AsyncSession``, but the
``LLMProviderChain`` fires log calls inside ``asyncio.create_task`` — after
the request session has already closed (R24 pattern).  This wrapper opens a
tiny short-lived session per ``log()`` call so the cost row is committed
independently of the request lifecycle.

Invariants:
  - All exceptions are swallowed and emitted as structlog WARN.
  - Implements ``LlmUsageLogProtocol`` structurally (no explicit subclassing).
  - Thread-safe: each ``log()`` opens its own session — no shared state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


class SessionScopedRagUsageLogger:
    """Fire-and-forget LLM usage logger backed by rag_chat_db.llm_usage_log.

    Implements ``LlmUsageLogProtocol`` structurally.  Each ``log()`` call
    opens a fresh ``AsyncSession``, delegates to
    :class:`~rag_chat.infrastructure.db.repositories.llm_usage_log.RagChatUsageLogRepository`,
    commits, and closes the session.

    Args:
    ----
        session_factory:  async_sessionmaker bound to the rag_chat_db write engine.

    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

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
        """Append one usage-log row in a short-lived session.

        Best-effort: any exception is swallowed and emitted as structlog WARN.
        The caller never sees an exception from this method.
        """
        try:
            from rag_chat.infrastructure.db.repositories.llm_usage_log import (
                RagChatUsageLogRepository,
            )

            async with self._sf() as session:
                repo = RagChatUsageLogRepository(session)
                await repo.log(
                    model_id=model_id,
                    provider=provider,
                    capability=capability,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                    estimated_cost_usd=estimated_cost_usd,
                    success=success,
                    error_code=error_code,
                    **context,
                )
                await session.commit()
        except Exception as exc:
            logger.warning(
                "rag_usage_log_session_scoped_failed",
                error=str(exc),
                exc_info=True,
            )
