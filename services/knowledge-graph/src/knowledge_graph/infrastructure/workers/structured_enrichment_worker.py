"""Worker 13J: Structured entity enrichment daily sweep (PRD-0073 §9.5).

Runs nightly at 02:00 UTC via APScheduler CronTrigger.  Iterates
``list_unenriched`` in pages of 50 until the queue is drained or 3 attempts
have been exhausted for every remaining entity.

Hot-path enrichment for freshly-created entities is handled by
:class:`StructuredEnrichmentConsumer` (entity.canonical.created.v1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from knowledge_graph.domain.errors import FatalEnrichmentError, RetryableEnrichmentError
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
            continue — the entity will be retried on the next cycle.
          - On FatalEnrichmentError or any other exception: increment
            enrichment_attempts so the entity eventually ages out.
          - Loop continues until list_unenriched returns an empty page.
        """
        enriched = 0
        failed = 0
        retryable = 0
        total_processed = 0

        while True:
            entities = await self._adapter.list_unenriched(batch_size=_BATCH_SIZE)
            if not entities:
                break

            for entity in entities:
                total_processed += 1
                try:
                    await self._use_case.enrich(entity)
                    enriched += 1
                except RetryableEnrichmentError as exc:
                    retryable += 1
                    logger.warning(  # type: ignore[no-any-return]
                        "structured_enrichment_worker_retryable",
                        entity_id=str(entity.entity_id),
                        error=str(exc),
                    )
                    # Do NOT increment attempts — retryable errors are transient
                except (FatalEnrichmentError, Exception) as exc:
                    failed += 1
                    logger.error(  # type: ignore[no-any-return]
                        "structured_enrichment_worker_fatal",
                        entity_id=str(entity.entity_id),
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    await self._increment_attempts(entity.entity_id)

        logger.info(  # type: ignore[no-any-return]
            "structured_enrichment_worker_complete",
            enriched=enriched,
            failed=failed,
            retryable=retryable,
            total_processed=total_processed,
        )

    async def _increment_attempts(self, entity_id: object) -> None:
        """Open a short-lived session to increment enrichment_attempts."""
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
