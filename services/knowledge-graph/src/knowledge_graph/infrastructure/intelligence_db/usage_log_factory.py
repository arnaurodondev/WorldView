"""Session-scoped KG usage logger (PLAN-0057 T-A-5-03).

Mirror of ``nlp_pipeline.infrastructure.nlp_db.usage_log_factory`` for the
knowledge-graph service.  Closes the KG side of audit finding F-CRIT-03 —
``intelligence_db.llm_usage_log`` was permanently empty despite ~50 KG-side
LLM calls every 30 minutes (FallbackChainClient embed/extract calls).

Why a "session-scoped" wrapper?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The KG ``LlmUsageLogRepository`` needs an open ``AsyncSession`` to INSERT,
but ``FallbackChainClient`` calls ``_log()`` AFTER releasing any session
(R24 — never hold a DB connection across external HTTP calls).  This
wrapper opens a fresh, short-lived session per ``log()`` call so callers
can stay session-free.

Invariants:
  - All exceptions are swallowed and logged at WARN with ``exc_info=True``.
  - Implements ``LlmUsageLogProtocol`` structurally.
  - Each ``log()`` opens, commits, and closes its own session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


class SessionScopedKgUsageLogger:
    """Fire-and-forget LLM usage logger backed by ``intelligence_db.llm_usage_log``.

    Implements ``LlmUsageLogProtocol`` structurally.  Each ``log()`` call
    opens a fresh ``AsyncSession`` from the injected factory, delegates to
    :class:`LlmUsageLogRepository`, commits, and closes the session.

    Args:
    ----
        session_factory:  async_sessionmaker bound to the intelligence_db
            write engine (the same factory the workers/consumers already use).

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
        cost_source: str | None = None,
        user_id: UUID | None = None,
        **context: object,
    ) -> None:
        """Append one usage-log row in a short-lived session.

        PLAN-0117 W3: threads ``cost_source`` (provenance of the cost) and
        ``user_id`` (NULL for KG background pipelines) into the row.

        Best-effort: any exception (DB unreachable, schema drift, etc.) is
        swallowed and emitted as a structlog WARN with ``exc_info=True``.
        """
        try:
            # Late import keeps the import graph minimal — only paid for when
            # the logger is actually invoked (i.e. an LLM call has happened).
            from knowledge_graph.infrastructure.intelligence_db.repositories.llm_usage_log import (
                LlmUsageLogRepository,
            )

            async with self._sf() as session:
                repo = LlmUsageLogRepository(session)
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
                    cost_source=cost_source,
                    user_id=user_id,
                    **context,
                )
                await session.commit()
        except Exception as exc:
            # Observer must never affect subject — log + continue.
            logger.warning(
                "kg_usage_log_session_scoped_failed",
                error=str(exc),
                exc_info=True,
            )
