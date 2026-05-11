"""ScheduleDueSourcesUseCase — scheduler tick for content ingestion.

Evaluates all enabled sources, checks watermarks and active-task guards,
and bulk-inserts tasks idempotently (ON CONFLICT DO NOTHING).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from content_ingestion.domain.entities import ContentIngestionTask, Source, SourceType
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


@dataclass
class SchedulerTickResult:
    """Summary of one scheduler tick."""

    tasks_enqueued: int = 0
    sources_evaluated: int = 0


class ScheduleDueSourcesUseCase:
    """Evaluate enabled sources and create ingestion tasks for those that are due.

    Idempotency: ``ON CONFLICT (source_id, window_start) DO NOTHING`` in the
    repository prevents duplicate tasks even when multiple scheduler instances
    run concurrently.

    Per-source-type interval overrides (``source_type_intervals``) allow
    rate-limited providers (e.g. NewsAPI 100 req/day) to use a longer polling
    cadence than the global ``scheduler_interval_seconds``.  BP-460.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        scheduler_interval_seconds: float = 300.0,
        max_tasks_per_tick: int = 100,
        # BP-460: map SourceType → override interval in seconds.
        # Keys absent from this dict fall back to scheduler_interval_seconds.
        source_type_intervals: dict[SourceType, float] | None = None,
    ) -> None:
        self._uow = uow
        self._interval = scheduler_interval_seconds
        self._max_tasks_per_tick = max_tasks_per_tick
        # Use an empty dict (not a mutable default) so callers can pass None safely.
        self._source_type_intervals: dict[SourceType, float] = source_type_intervals or {}

    def _interval_for(self, source_type: SourceType) -> float:
        """Return the effective polling interval for a given source type.

        Falls back to the global ``scheduler_interval_seconds`` when no
        per-type override is registered.
        """
        return self._source_type_intervals.get(source_type, self._interval)

    async def execute(self) -> SchedulerTickResult:
        """Run one scheduler tick and return a summary."""
        result = SchedulerTickResult()
        now = utc_now()

        async with self._uow:
            # 1. Load all enabled sources
            source_models = await self._uow.sources.list_enabled()
            result.sources_evaluated = len(source_models)

            if not source_models:
                logger.info("scheduler_tick_no_sources")
                await self._uow.commit()
                return result

            # 2. For each source, check if due
            candidate_tasks: list[ContentIngestionTask] = []
            for model in source_models:
                source = Source(
                    id=model.id,
                    name=model.name,
                    source_type=SourceType(model.source_type),
                    enabled=model.enabled,
                    config=model.config,
                    created_at=model.created_at,
                )

                # Skip if source already has an active task
                if await self._uow.tasks.has_active_task(source.id):
                    logger.debug("scheduler_skip_active_task", source=source.name)
                    continue

                # Check watermark to determine if source is due.
                # Use the per-source-type interval override when configured
                # (e.g. NewsAPI uses 14 400 s instead of the global default).
                effective_interval = self._interval_for(source.source_type)
                state = await self._uow.adapter_state.get(source.id)
                if state and state.last_run_at:
                    elapsed = (now - state.last_run_at).total_seconds()
                    if elapsed < effective_interval:
                        logger.debug(
                            "scheduler_skip_not_due",
                            source=source.name,
                            elapsed=round(elapsed, 1),
                            interval=effective_interval,
                        )
                        continue

                task = ContentIngestionTask.create_for_source(source, window_start=now)
                candidate_tasks.append(task)

            # 3. Bulk insert (idempotent), respect cap
            final_tasks = candidate_tasks[: self._max_tasks_per_tick]
            if final_tasks:
                inserted = await self._uow.tasks.add_many_idempotent(final_tasks)
                result.tasks_enqueued = inserted

            await self._uow.commit()

        logger.info(
            "scheduler_tick_complete",
            sources_evaluated=result.sources_evaluated,
            tasks_enqueued=result.tasks_enqueued,
        )
        return result
