"""TriggerSourceUseCase — trigger an immediate fetch cycle for a source."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from content_ingestion.domain.entities import ContentIngestionTask, Source, SourceType
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from content_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


@dataclass(frozen=True)
class TriggerResult:
    """DTO for the trigger response."""

    source_id: UUID
    task_id: UUID


class TriggerSourceUseCase:
    """Trigger an immediate fetch cycle by creating a task for a source.

    Creates a task row that a worker will pick up — no fire-and-forget (R22).
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, source_id: UUID) -> TriggerResult | None:
        """Trigger a fetch. Returns None if source not found."""
        async with self._uow:
            source_model = await self._uow.sources.get_by_id(source_id)
            if source_model is None:
                return None

            source = Source(
                id=source_model.id,
                name=source_model.name,
                source_type=SourceType(source_model.source_type),
                enabled=source_model.enabled,
                config=source_model.config,
                created_at=source_model.created_at,
            )
            task = ContentIngestionTask.create_for_source(source, window_start=utc_now())
            await self._uow.tasks.add(task)
            await self._uow.commit()

        logger.info("source_triggered", source_id=str(source_id), task_id=str(task.id))
        return TriggerResult(source_id=source_id, task_id=task.id)
