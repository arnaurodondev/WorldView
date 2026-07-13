"""Session-scoped NLP usage logger (PLAN-0057 T-A-5-01).

Closes audit finding F-CRIT-03 (``nlp_db.llm_usage_log`` permanently empty
despite ~50 LLM calls every 30 minutes plus deep-extraction calls).

Why a "session-scoped" wrapper?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``NlpUsageLogRepository`` requires an open ``AsyncSession`` to write a row,
but most LLM call sites (workers, consumers, deep-extraction) do **not** hold
a session at the moment they finish an HTTP call (R24 — sessions are closed
before external I/O).  Rather than thread a session into every adapter, this
helper accepts a session **factory** at construction and opens a tiny,
short-lived session per ``log()`` call.

Invariants:
  - All exceptions are swallowed and logged at WARN with ``exc_info=True``.
    A cost-logging failure must never disrupt the main processing path.
  - Implements ``LlmUsageLogProtocol`` structurally (no explicit subclassing).
  - Each ``log()`` opens its own session, commits, and closes — no shared
    state between calls (safe for fire-and-forget ``asyncio.create_task``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


class SessionScopedNlpUsageLogger:
    """Fire-and-forget LLM usage logger backed by ``nlp_db.llm_usage_log``.

    Implements ``LlmUsageLogProtocol`` structurally.  Each ``log()`` call
    opens a fresh ``AsyncSession`` from the injected factory, delegates to
    :class:`NlpUsageLogRepository`, commits, and closes the session.

    Args:
    ----
        session_factory:  async_sessionmaker bound to the nlp_db write engine.

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

        PLAN-0117 W3: ``cost_source`` (provenance of ``estimated_cost_usd``) and
        ``user_id`` are now threaded to the row. Callers resolve the real cost +
        source via :func:`ml_clients.pricing.resolve_cost` — this logger no longer
        relies on the ``estimated_cost_usd=0.0`` default to mask an unpriced call.

        Best-effort: any exception (DB unreachable, schema drift, etc.) is
        swallowed and emitted as a structlog WARN with ``exc_info=True``.
        The caller never sees an exception.
        """
        try:
            # Late import keeps import-time graph minimal; the repo module is
            # only needed when an LLM call is actually being logged.
            from nlp_pipeline.infrastructure.nlp_db.repositories.llm_usage_log import (
                NlpUsageLogRepository,
            )

            async with self._sf() as session:
                repo = NlpUsageLogRepository(session)
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
                "nlp_usage_log_session_scoped_failed",
                error=str(exc),
                exc_info=True,
            )
