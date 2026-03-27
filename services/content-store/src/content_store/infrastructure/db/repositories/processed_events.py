"""ProcessedEventsRepository — idempotency store for the article consumer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from content_store.infrastructure.db.models import ProcessedEventModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class ProcessedEventsRepository:
    """Tracks event IDs that have already been processed.

    Used by ArticleConsumer to implement at-least-once idempotency:
    before processing a message the consumer checks ``is_duplicate``;
    after the DB writes succeed (inside the UoW) it calls ``mark_processed``
    so the event is never re-processed on retry.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_duplicate(self, event_id: str) -> bool:
        """Return True if *event_id* has already been processed.

        Args:
            event_id: String event ID from the Kafka message envelope.

        Returns:
            True if the event was previously processed; False otherwise.
        """
        from uuid import UUID

        try:
            parsed: UUID = UUID(event_id)
        except (ValueError, AttributeError):
            return False

        result = await self._session.execute(select(ProcessedEventModel).where(ProcessedEventModel.event_id == parsed))
        return result.scalar_one_or_none() is not None

    async def mark_processed(self, event_id: str) -> None:
        """Record *event_id* as successfully processed.

        Must be called inside the same transaction as the article DB writes
        so the dedup record is committed atomically.

        Args:
            event_id: String event ID from the Kafka message envelope.
        """
        from uuid import UUID

        try:
            parsed: UUID = UUID(event_id)
        except (ValueError, AttributeError):
            return

        self._session.add(ProcessedEventModel(event_id=parsed))
