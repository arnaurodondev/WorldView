"""RetryDLQEntryUseCase — requeue a DLQ entry back into the outbox."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from content_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


@dataclass(frozen=True)
class RetryResult:
    """DTO for the retry response."""

    new_event_id: UUID


class RetryDLQEntryUseCase:
    """Requeue a DLQ entry back into the outbox for re-delivery."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, dlq_id: UUID) -> RetryResult | None:
        """Requeue. Returns None if DLQ entry not found."""
        async with self._uow:
            entry = await self._uow.dlq.get_by_id(dlq_id)
            if entry is None:
                return None
            new_id = await self._uow.dlq.requeue(dlq_id)
            await self._uow.commit()

        logger.info("dlq_entry_requeued", dlq_id=str(dlq_id), new_event_id=str(new_id))
        return RetryResult(new_event_id=new_id)  # type: ignore[arg-type]
