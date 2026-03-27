"""Dead-letter queue repository for nlp_db (BP-020: insert row, don't just update status)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import common.ids  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.models import DeadLetterQueueModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class DLQRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def move_to_dlq(
        self,
        original_event_id: UUID,
        topic: str,
        payload_avro: bytes,
        error_detail: str | None = None,
    ) -> UUID:
        """Insert a new DLQ row for an unrecoverable event (BP-020: always INSERT).

        Returns the new dlq_id.
        """
        dlq_id = common.ids.new_uuid7()
        row = DeadLetterQueueModel(
            dlq_id=dlq_id,
            original_event_id=original_event_id,
            topic=topic,
            payload_avro=payload_avro,
            error_detail=error_detail,
            status="failed",
        )
        self._session.add(row)
        return dlq_id
