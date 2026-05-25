"""Worker 13J: Structured entity enrichment daily sweep (PRD-0073 §9.5).

Runs nightly at 02:00 UTC via APScheduler CronTrigger.  Iterates
``list_unenriched`` in pages of 50 until the queue is drained or 3 attempts
have been exhausted for every remaining entity.

Hot-path enrichment for freshly-created entities is handled by
:class:`StructuredEnrichmentConsumer` (entity.canonical.created.v1).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from knowledge_graph.domain.errors import FatalEnrichmentError, RetryableEnrichmentError
from knowledge_graph.infrastructure.metrics.prometheus import (
    s7_enrichment_entities_total,
    s7_enrichment_sweep_entities_processed_total,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.application.use_cases.structured_enrichment import (
        StructuredEnrichmentUseCase,
    )
    from knowledge_graph.infrastructure.intelligence_db.adapters.entity_enrichment_adapter import (
        EntityEnrichmentAdapter,
    )

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BATCH_SIZE = 50

# F-X04 (PLAN-0073 fix): cap consecutive retryable failures (e.g. EODHD 429
# storms) before we abort the sweep and let the next nightly run try again.
_MAX_CONSECUTIVE_RETRYABLE = 3
# Bounded sleep cap between retryables — exponential 2 ** consecutive (1, 2, 4
# seconds) but never more than 60s so a stuck sweep cannot hold the worker open
# indefinitely.
_RETRYABLE_SLEEP_CAP_S = 60


class StructuredEnrichmentWorker:
    """Nightly catch-up sweep for unenriched canonical entities (Worker 13J).

    Args:
        enrichment_adapter: Port implementation for listing unenriched entities
                            and incrementing attempts.
        use_case:           Orchestration use case (3-phase cascade).
        session_factory:    async_sessionmaker for Phase 3 DB writes (attempt
                            increments open their own session).
    """

    def __init__(
        self,
        enrichment_adapter: EntityEnrichmentAdapter,
        use_case: StructuredEnrichmentUseCase,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._adapter = enrichment_adapter
        self._use_case = use_case
        self._sf = session_factory

    async def run(self) -> None:
        """Drain the unenriched entity queue in batches of 50.

        Processing loop:
          - Fetch up to _BATCH_SIZE entities eligible for enrichment.
          - For each entity, call use_case.enrich().
          - On RetryableEnrichmentError: skip (do NOT increment attempts) and
            apply bounded exponential backoff between consecutive retryables;
            abort the whole sweep after _MAX_CONSECUTIVE_RETRYABLE in a row to
            avoid a 429 storm hammering EODHD/LLM (F-X04).
          - On FatalEnrichmentError or any other exception: increment
            enrichment_attempts so the entity eventually ages out (F-X22:
            keep a single ``except Exception`` since FatalEnrichmentError is a
            subclass — the previous tuple was tautological).
          - Loop continues until list_unenriched returns an empty page.
        """
        enriched = 0
        failed = 0
        retryable = 0
        total_processed = 0
        consecutive_retryable = 0
        aborted_due_to_retryables = False

        while True:
            # PLAN-0093 T-C-4-01 (F-DB-ENRICHMENT-001): use the atomic
            # claim-and-increment so attempts advances exactly once per real
            # processing attempt — even if the worker crashes mid-enrichment
            # OR two workers race on the same entity. The old SELECT-then-
            # later-UPDATE flow let attempts get stuck at 0 forever (audit
            # 2026-05-23 found 1,790 of 5,230 entities had attempts=0 + no
            # enriched_at).
            entities = await self._adapter.claim_for_enrichment(batch_size=_BATCH_SIZE)
            if not entities:
                break

            for entity in entities:
                total_processed += 1
                try:
                    await self._use_case.enrich(entity)
                    enriched += 1
                    # F-A07 / F-P2-02: success path metric.  The use case also
                    # bumps ``s7_enrichment_entities_total`` from the consumer
                    # path; the sweep counter is what tells us how the catch-up
                    # job specifically is doing.
                    s7_enrichment_sweep_entities_processed_total.labels(outcome="success").inc()
                    # Reset the streak counter on any successful enrichment so a
                    # single 429 burst does not permanently abort the sweep.
                    consecutive_retryable = 0
                except RetryableEnrichmentError as exc:
                    retryable += 1
                    consecutive_retryable += 1
                    logger.warning(  # type: ignore[no-any-return]
                        "structured_enrichment_worker_retryable",
                        entity_id=str(entity.entity_id),
                        error=str(exc),
                        consecutive=consecutive_retryable,
                    )
                    # F-A07 / F-P2-02: retryable outcome metrics.
                    s7_enrichment_entities_total.labels(entity_type=entity.entity_type, outcome="retryable").inc()
                    s7_enrichment_sweep_entities_processed_total.labels(outcome="retryable").inc()
                    # PLAN-0093 T-C-4-01: rollback the claim-time increment so
                    # retryable failures don't burn an attempt (preserves the
                    # pre-existing semantic that transient errors are not
                    # evidence of unfixable entity state).
                    await self._decrement_attempts(entity.entity_id)
                    if consecutive_retryable >= _MAX_CONSECUTIVE_RETRYABLE:
                        # F-X04: bail out — tomorrow's run will pick up the
                        # remaining queue.  This protects EODHD's 100k/day quota
                        # and prevents a positive-feedback retry storm.
                        logger.error(  # type: ignore[no-any-return]
                            "structured_enrichment_worker_aborted_consecutive_retryables",
                            consecutive=consecutive_retryable,
                            processed=total_processed,
                        )
                        aborted_due_to_retryables = True
                        break
                    # Exponential backoff before the next entity.
                    sleep_s = min(_RETRYABLE_SLEEP_CAP_S, 2 ** (consecutive_retryable - 1))
                    await asyncio.sleep(sleep_s)
                except Exception as exc:
                    failed += 1
                    consecutive_retryable = 0  # any non-retryable resets streak
                    logger.error(  # type: ignore[no-any-return]
                        "structured_enrichment_worker_fatal",
                        entity_id=str(entity.entity_id),
                        error_type=type(exc).__name__,
                        is_fatal_subclass=isinstance(exc, FatalEnrichmentError),
                        error=str(exc),
                    )
                    # F-A07 / F-P2-02: fatal outcome metrics.
                    s7_enrichment_entities_total.labels(entity_type=entity.entity_type, outcome="fatal").inc()
                    s7_enrichment_sweep_entities_processed_total.labels(outcome="fatal").inc()
                    # PLAN-0093 T-C-4-01: do NOT call _increment_attempts here —
                    # claim_for_enrichment already bumped the counter at claim time.
                    # Calling it again would double-charge the entity and exhaust
                    # the 3-attempt budget after just 2 real failures.

            if aborted_due_to_retryables:
                break

        logger.info(  # type: ignore[no-any-return]
            "structured_enrichment_worker_complete",
            enriched=enriched,
            failed=failed,
            retryable=retryable,
            total_processed=total_processed,
            aborted_due_to_retryables=aborted_due_to_retryables,
        )

    async def _increment_attempts(self, entity_id: object) -> None:
        """Open a short-lived session to increment enrichment_attempts.

        Kept for backwards-compatibility with callers outside the sweep loop
        (e.g. one-off remediation scripts). The sweep loop itself no longer
        calls this — claim_for_enrichment handles the +1 atomically at claim.
        """
        from uuid import UUID

        try:
            async with self._sf() as session:
                await self._adapter.increment_attempts(UUID(str(entity_id)), session)
                await session.commit()
        except Exception:
            logger.error(  # type: ignore[no-any-return]
                "structured_enrichment_worker_increment_failed",
                entity_id=str(entity_id),
                exc_info=True,
            )

    async def _decrement_attempts(self, entity_id: object) -> None:
        """PLAN-0093 T-C-4-01: rollback a claim-time increment after a
        RetryableEnrichmentError so transient failures don't burn an attempt.
        """
        from uuid import UUID

        try:
            async with self._sf() as session:
                await self._adapter.decrement_attempts(UUID(str(entity_id)), session)
                await session.commit()
        except Exception:
            logger.error(  # type: ignore[no-any-return]
                "structured_enrichment_worker_decrement_failed",
                entity_id=str(entity_id),
                exc_info=True,
            )
