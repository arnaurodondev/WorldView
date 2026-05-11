"""EmbeddingPendingRepository — save and claim failed embedding entries.

Used by:
  - ArticleProcessingConsumer: saves EmbeddingPendingEntry records when
    Block 7 embedding calls fail.
  - EmbeddingRetryWorker: claims batches and retries with exponential backoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

import common.ids  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.models import EmbeddingPendingModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import EmbeddingPendingEntry


@dataclass
class RetryJob:
    """A claimed pending-embedding row ready to be re-processed."""

    pending_id: UUID
    doc_id: UUID
    section_id: UUID | None
    chunk_id: UUID | None
    embedding_text: str
    retry_count: int


class EmbeddingPendingRepository:
    """Read/write the embedding_pending retry queue in nlp_db."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_batch(self, entries: list[EmbeddingPendingEntry]) -> None:
        """Insert a list of EmbeddingPendingEntry rows into the retry queue."""
        for entry in entries:
            self._session.add(
                EmbeddingPendingModel(
                    pending_id=common.ids.new_uuid7(),  # type: ignore[arg-type]
                    doc_id=entry.doc_id,
                    section_id=entry.section_id,
                    chunk_id=entry.chunk_id,
                    embedding_text=entry.embedding_text,
                    error_detail=entry.error_detail,
                    retry_count=0,
                    next_retry_at=entry.created_at,
                    created_at=entry.created_at,
                )
            )

    async def claim_batch(self, batch_size: int = 16, max_retries: int = 5) -> list[RetryJob]:
        """Return up to *batch_size* pending rows due for retry.

        Rows are ordered by ``next_retry_at ASC`` so the oldest overdue
        failures are retried first.  Rows that have already reached
        *max_retries* are excluded — they are abandoned in place and
        should be reviewed manually.

        ``FOR UPDATE SKIP LOCKED`` (PLAN-0057 QA H-3): when more than one
        retry-worker container runs (scaling, blue/green deploys, the
        standalone process plus a stray scheduler tick) the claim must be
        partition-safe.  SKIP LOCKED makes each worker instantly skip rows
        another worker is currently processing instead of blocking on the
        row-level lock — no double increments of ``retry_count``, no two
        workers writing the same embedding twice.
        """
        result = await self._session.execute(
            text(
                "SELECT pending_id, doc_id, section_id, chunk_id, embedding_text, retry_count "
                "FROM embedding_pending "
                "WHERE retry_count < :max_retries "
                "  AND next_retry_at <= now() "
                "ORDER BY next_retry_at ASC "
                "LIMIT :batch_size "
                "FOR UPDATE SKIP LOCKED"
            ),
            {"max_retries": max_retries, "batch_size": batch_size},
        )
        rows = result.fetchall()
        from uuid import UUID

        return [
            RetryJob(
                pending_id=UUID(str(row[0])),
                doc_id=UUID(str(row[1])),
                section_id=UUID(str(row[2])) if row[2] else None,
                chunk_id=UUID(str(row[3])) if row[3] else None,
                embedding_text=str(row[4]),
                retry_count=int(row[5]),
            )
            for row in rows
        ]

    async def mark_success(self, pending_id: UUID) -> None:
        """Delete a pending entry after a successful retry."""
        await self._session.execute(
            text("DELETE FROM embedding_pending WHERE pending_id = :pending_id"),
            {"pending_id": str(pending_id)},
        )

    async def mark_failure(self, pending_id: UUID, backoff_seconds: float) -> None:
        """Increment retry_count, schedule the next retry, and stamp last_attempted_at.

        ``last_attempted_at`` (added in migration 0016, PLAN-0057 Wave E-4)
        captures wall-clock time of the most recent attempt so operators can
        diagnose stuck queues without having to infer from ``next_retry_at``.
        """
        await self._session.execute(
            text(
                "UPDATE embedding_pending "
                "SET retry_count = retry_count + 1, "
                "    next_retry_at = now() + cast(:backoff AS float) * interval '1 second', "
                "    last_attempted_at = now() "
                "WHERE pending_id = :pending_id"
            ),
            {"pending_id": str(pending_id), "backoff": backoff_seconds},
        )

    async def count_abandoned(self, max_retries: int = 5) -> int:
        """Return how many rows have been retried ``>= max_retries`` times.

        These rows are silently skipped by ``claim_batch`` until manual triage;
        the entry-point logs the count at startup so the metric never goes dark.
        """
        result = await self._session.execute(
            text("SELECT COUNT(*) FROM embedding_pending WHERE retry_count >= :max_retries"),
            {"max_retries": max_retries},
        )
        return int(result.scalar_one())

    async def count_pending(self) -> int:
        """Return total count of rows still in the retry queue."""
        result = await self._session.execute(text("SELECT COUNT(*) FROM embedding_pending"))
        return int(result.scalar_one())
