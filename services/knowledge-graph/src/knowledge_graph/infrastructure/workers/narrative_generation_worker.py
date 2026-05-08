"""Worker 13D-3: Entity narrative generation (PRD-0074 §13.3).

Iterates over a list of entity IDs and calls ``GenerateNarrativeUseCase.execute``
for each, with bounded concurrency (asyncio.Semaphore(5) by default).

Trigger modes:
  - PERIODIC_REFRESH: APScheduler cron job ``0 3 * * 0`` (weekly, Sunday 3 AM UTC).
    Registered in ``KnowledgeGraphScheduler._register_jobs``.
  - INITIAL / MANUAL_TRIGGER: callable directly by passing ``entity_ids`` to
    ``run_batch``.  No APScheduler involvement.

The worker itself is a thin orchestrator.  All logic lives in
``GenerateNarrativeUseCase``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID

from knowledge_graph.domain.narrative import NarrativeGenerationReason
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from knowledge_graph.application.use_cases.generate_narrative import GenerateNarrativeUseCase

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Maximum concurrent narrative generation calls (prevents overwhelming the LLM).
_DEFAULT_CONCURRENCY = 5


class NarrativeGenerationWorker:
    """Orchestrates batch narrative generation for a set of entity IDs (Worker 13D-3).

    Args:
    ----
        use_case:    :class:`~knowledge_graph.application.use_cases.generate_narrative.GenerateNarrativeUseCase`
                     instance to delegate generation to.
        concurrency: Maximum parallel ``use_case.execute`` calls.
                     Defaults to ``_DEFAULT_CONCURRENCY`` (5).

    """

    def __init__(
        self,
        use_case: GenerateNarrativeUseCase,
        concurrency: int = _DEFAULT_CONCURRENCY,
    ) -> None:
        self._use_case = use_case
        self._semaphore = asyncio.Semaphore(concurrency)

    # ── Main entry points ─────────────────────────────────────────────────────

    async def run_batch(
        self,
        entity_ids: list[UUID],
        reason: NarrativeGenerationReason = NarrativeGenerationReason.PERIODIC_REFRESH,
        tenant_id: UUID | None = None,
    ) -> dict[str, int]:
        """Generate narratives for a batch of entities.

        Calls ``use_case.execute`` for each entity ID with bounded concurrency.
        Returns a summary dict: ``{"generated": N, "skipped": M, "failed": K}``.

        Args:
        ----
            entity_ids: List of canonical entity UUIDs to process.
            reason:     Trigger reason for this generation pass.
            tenant_id:  Optional tenant scope (passed through to the use case).

        """
        if not entity_ids:
            logger.info(  # type: ignore[no-any-return]
                "narrative_generation_worker_batch_empty",
                reason=reason.value,
            )
            return {"generated": 0, "skipped": 0, "failed": 0}

        logger.info(  # type: ignore[no-any-return]
            "narrative_generation_worker_batch_start",
            entity_count=len(entity_ids),
            reason=reason.value,
        )

        counters: dict[str, int] = {"generated": 0, "skipped": 0, "failed": 0}
        lock = asyncio.Lock()

        async def _process_one(entity_id: UUID) -> None:
            async with self._semaphore:
                try:
                    generated = await self._use_case.execute(
                        entity_id=entity_id,
                        tenant_id=tenant_id,
                        reason=reason.value,
                    )
                    async with lock:
                        if generated:
                            counters["generated"] += 1
                        else:
                            counters["skipped"] += 1
                except Exception:
                    logger.exception(  # type: ignore[no-any-return]
                        "narrative_generation_worker_entity_failed",
                        entity_id=str(entity_id),
                        reason=reason.value,
                    )
                    async with lock:
                        counters["failed"] += 1

        await asyncio.gather(*[_process_one(eid) for eid in entity_ids])

        logger.info(  # type: ignore[no-any-return]
            "narrative_generation_worker_batch_complete",
            reason=reason.value,
            **counters,
        )
        return counters

    async def run(self) -> None:
        """APScheduler-compatible periodic sweep (PERIODIC_REFRESH).

        Fetches all canonical entities and runs narrative generation for those
        that are missing a current narrative or whose narrative is stale
        (no current_narrative_version_id set on canonical_entities).

        This method is registered by the scheduler factory.
        """
        entity_ids = await self._fetch_stale_entities()
        if entity_ids:
            await self.run_batch(entity_ids, reason=NarrativeGenerationReason.PERIODIC_REFRESH)
        else:
            logger.info(  # type: ignore[no-any-return]
                "narrative_generation_worker_no_stale_entities",
            )

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _fetch_stale_entities(self) -> list[UUID]:
        """Fetch entities that have no current narrative version.

        Uses the use_case's write session factory to run the SELECT.
        Returns up to 500 entity IDs per sweep to bound run time.
        """
        from sqlalchemy import text

        try:
            async with self._use_case._read_sf() as session:  # type: ignore[attr-defined]
                result = await session.execute(
                    text("""
SELECT entity_id
FROM canonical_entities
WHERE current_narrative_version_id IS NULL
ORDER BY entity_id
LIMIT 500
"""),
                )
                rows = result.fetchall()
                return [UUID(str(row[0])) for row in rows]
        except Exception:
            logger.exception(  # type: ignore[no-any-return]
                "narrative_generation_worker_fetch_stale_failed",
            )
            return []
