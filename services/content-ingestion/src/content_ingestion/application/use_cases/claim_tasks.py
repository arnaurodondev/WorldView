"""ClaimTasksUseCase — atomically claim a batch of content ingestion tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.application.ports.unit_of_work import UnitOfWork
    from content_ingestion.domain.entities import ContentIngestionTask

logger = get_logger(__name__)


class ClaimTasksUseCase:
    """Atomically claim a batch of PENDING or RETRY tasks for a worker.

    Delegates entirely to ``TaskRepository.claim_batch``; the repository
    implementation uses ``SELECT … FOR UPDATE SKIP LOCKED``.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        worker_id: str,
        batch_size: int,
        lease_seconds: int = 300,
    ) -> list[ContentIngestionTask]:
        """Claim up to *batch_size* tasks for *worker_id*.

        Args:
            worker_id: Unique identifier for the calling worker process.
            batch_size: Maximum number of tasks to claim.
            lease_seconds: Duration of the worker lease in seconds.

        Returns:
            List of claimed tasks (status=CLAIMED, lease set).
        """
        async with self._uow:
            tasks = await self._uow.tasks.claim_batch(
                worker_id=worker_id,
                limit=batch_size,
                lease_seconds=lease_seconds,
            )
            await self._uow.commit()

        logger.info(
            "tasks_claimed",
            worker_id=worker_id,
            claimed=len(tasks),
            requested=batch_size,
        )
        return tasks
