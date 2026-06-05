"""Prometheus + DB-backed CostRecorder (PLAN-0107 follow-up — agent-B mission).

Concrete implementation of :class:`rag_chat.application.ports.cost_recorder.CostRecorder`.

For every LLM call this recorder:
  1. Calls ``compute_cost(model_id, tokens_in, tokens_out)`` from
     ``libs/ml-clients/pricing.py`` — the canonical, Decimal-based pricing
     matrix.
  2. Increments the bounded Prometheus counter
     ``rag_chat_ml_api_estimated_cost_usd_total{model_id, call_site}`` —
     this is the metric the Grafana panel id=6 has been querying since
     ship, but the counter wasn't registered (the panel rendered empty).
  3. Persists a row to ``llm_usage_log`` via the existing
     ``RagChatUsageLogRepository``, populating the ``estimated_cost_usd``
     column for the first time (it was hard-coded to 0.0 everywhere).
  4. If ``thread_id`` is provided, atomically bumps
     ``chat_threads.estimated_cost_usd`` via a single SQL UPDATE
     (read-modify-write would race against concurrent message turns).

All exceptions are caught and logged at WARNING — a cost-recording failure
must NEVER break the chat path.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from ml_clients.pricing import compute_cost  # type: ignore[import-untyped]

from rag_chat.application.metrics.prometheus import (
    rag_chat_ml_api_estimated_cost_usd_total,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


# Type alias for a callable that builds a new write-side AsyncSession.
# WHY a factory rather than a session: the recorder is shared across the app
# lifetime; sessions are per-request. The factory lets us open and CLOSE a
# fresh session for each ``record()`` call so we don't leak DB connections
# or interfere with an outer transaction managed by the request scope.
SessionFactory = "Callable[[], AsyncSession]"


class PrometheusAndDbCostRecorder:
    """Production CostRecorder — Prometheus + ``llm_usage_log`` + thread bump.

    Constructor injects a write-session factory (typically
    ``app.state.write_factory``) and an optional default provider tag that
    is persisted on every ``llm_usage_log`` row. ``provider`` is informational
    for the usage log; pricing is keyed solely on ``model_id``.
    """

    def __init__(
        self,
        write_session_factory: Callable[[], AsyncSession],
        *,
        provider: str = "deepinfra",
    ) -> None:
        # Stored callables — never invoked at construction so the recorder
        # can be wired before the DB engine is healthy.
        self._session_factory = write_session_factory
        self._default_provider = provider

    async def record(
        self,
        *,
        thread_id: UUID | None,
        model_id: str,
        tokens_in: int,
        tokens_out: int,
        call_site: str,
    ) -> None:
        """Record cost for one LLM call. Never raises."""
        # 1. Compute the USD cost. ``compute_cost`` itself logs a warning
        #    and returns Decimal("0") for unknown models — that's fine; we
        #    still bump the counter (with value 0) so the model_id is
        #    visible in the metric (operators can spot the unknown pricing).
        try:
            cost = compute_cost(model_id, tokens_in, tokens_out)
        except Exception as exc:  # noqa: BLE001 — must never propagate
            log.warning(  # type: ignore[no-any-return]
                "cost_recorder_pricing_failed",
                model_id=model_id,
                call_site=call_site,
                error=str(exc),
            )
            cost = Decimal("0")

        # 2. Increment the Prometheus counter. prometheus_client accepts
        #    float only — convert from Decimal at the boundary. Float-drift
        #    here is acceptable because Prometheus is approximate by design;
        #    the DB column keeps the exact Decimal.
        try:
            rag_chat_ml_api_estimated_cost_usd_total.labels(
                model_id=model_id,
                call_site=call_site,
            ).inc(float(cost))
        except Exception as exc:  # noqa: BLE001 — must never propagate
            log.warning(  # type: ignore[no-any-return]
                "cost_recorder_metric_failed",
                model_id=model_id,
                call_site=call_site,
                error=str(exc),
            )

        # 3 + 4. DB writes — both share a single short-lived session for
        #         transactional consistency. If either fails the entire DB
        #         path is swallowed; the metric was already incremented so
        #         dashboards stay accurate.
        try:
            await self._persist(
                thread_id=thread_id,
                model_id=model_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                call_site=call_site,
                cost=cost,
            )
        except Exception as exc:  # noqa: BLE001 — must never propagate
            log.warning(  # type: ignore[no-any-return]
                "cost_recorder_db_failed",
                model_id=model_id,
                call_site=call_site,
                thread_id=str(thread_id) if thread_id else None,
                error=str(exc),
            )

    async def _persist(
        self,
        *,
        thread_id: UUID | None,
        model_id: str,
        tokens_in: int,
        tokens_out: int,
        call_site: str,
        cost: Decimal,
    ) -> None:
        """Open a fresh write session, append the usage row + bump the thread."""
        # Local import keeps the module importable from contexts where the
        # repository module isn't loaded yet (e.g. unit tests stubbing DB).
        from rag_chat.infrastructure.db.repositories.llm_usage_log import (
            RagChatUsageLogRepository,
        )

        session = self._session_factory()
        try:
            # Usage-log row — the existing repository already swallows its
            # own exceptions, but we wrap defensively so the outer try in
            # ``record`` is the single catch-all.
            repo = RagChatUsageLogRepository(session)
            # capability=call_site is intentional: ``capability`` is the
            # legacy field on ``llm_usage_log``; we re-use the bounded
            # ``call_site`` enum so dashboards can join across columns.
            await repo.log(
                model_id=model_id,
                provider=self._default_provider,
                capability=call_site,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=0,  # the recorder is not the right place to measure latency
                estimated_cost_usd=float(cost),
                success=True,
                chat_thread_id=thread_id,
            )

            # Atomic per-thread bump via single UPDATE. NEVER read-then-write
            # — two concurrent message turns would race and one update would
            # be lost. ``COALESCE(estimated_cost_usd, 0)`` handles the first
            # turn on a thread whose column is still NULL.
            if thread_id is not None:
                from sqlalchemy import text

                await session.execute(
                    text(
                        """
                        UPDATE threads
                        SET estimated_cost_usd =
                            COALESCE(estimated_cost_usd, 0) + :cost
                        WHERE thread_id = :thread_id
                        """,
                    ),
                    {"cost": cost, "thread_id": str(thread_id)},
                )

            # Commit the in-session writes (the existing repo only flushes).
            await session.commit()
        finally:
            await session.close()


__all__ = ["PrometheusAndDbCostRecorder"]
