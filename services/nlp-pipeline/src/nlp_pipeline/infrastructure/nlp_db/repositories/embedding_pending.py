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

    async def mark_failure(self, pending_id: UUID, backoff_seconds: float, *, increment_retry: bool = True) -> None:
        """Schedule the next retry, stamp last_attempted_at, and (by default) bump retry_count.

        ``last_attempted_at`` (added in migration 0016, PLAN-0057 Wave E-4)
        captures wall-clock time of the most recent attempt so operators can
        diagnose stuck queues without having to infer from ``next_retry_at``.

        ``increment_retry`` (default ``True``): pass ``False`` for a
        :class:`ml_clients.errors.ProviderBillingError` (HTTP 402 spend-cap / 401/403
        auth refusal). Such a failure is NOT the row's fault and clears only when the
        operator raises the cap, so consuming the bounded 5-attempt budget on it would
        permanently abandon otherwise-valid work during a multi-hour cap-down. Leaving
        ``retry_count`` untouched lets the row keep re-attempting (bounded only by the
        backoff schedule) so it self-heals the instant the cap is raised.
        """
        retry_count_expr = "retry_count + 1" if increment_retry else "retry_count"
        await self._session.execute(
            text(
                "UPDATE embedding_pending "
                f"SET retry_count = {retry_count_expr}, "
                "    next_retry_at = now() + cast(:backoff AS float) * interval '1 second', "
                "    last_attempted_at = now() "
                "WHERE pending_id = :pending_id"
            ),
            {"pending_id": str(pending_id), "backoff": backoff_seconds},
        )

    async def mark_abandoned(self, pending_id: UUID, *, max_retries: int, error_detail: str) -> None:
        """Permanently abandon a pending row after a fatal (non-retryable) error.

        Jumps ``retry_count`` straight to *max_retries* so ``claim_batch`` will
        never re-claim the row (identical skip semantics to natural retry
        exhaustion, and ``count_abandoned`` still counts it) and records the
        terminating error in ``error_detail``.

        Used for HTTP 4xx (bad-input) embedding failures — empty/degenerate
        text or still-oversized input — which can never succeed on retry.  This
        short-circuits the full exponential-backoff schedule (5 attempts over
        ~2 h) that would otherwise be wasted on a request guaranteed to return
        400.  Transient errors (5xx / timeout / 429) still go through
        ``mark_failure`` and keep their backoff-retry behaviour.
        """
        await self._session.execute(
            text(
                "UPDATE embedding_pending "
                "SET retry_count = :max_retries, "
                "    next_retry_at = now(), "
                "    last_attempted_at = now(), "
                "    error_detail = :error_detail "
                "WHERE pending_id = :pending_id"
            ),
            {
                "pending_id": str(pending_id),
                "max_retries": max_retries,
                # Cap the stored detail so a verbose upstream error body can't
                # bloat the row (error_detail is diagnostic, not load-bearing).
                "error_detail": error_detail[:1000],
            },
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

    async def requeue_abandoned(self, *, max_retries: int = 5, limit: int = 500) -> int:
        """Reset up to *limit* abandoned rows so ``claim_batch`` picks them up again.

        An "abandoned" row is one with ``retry_count >= max_retries`` — silently
        skipped by ``claim_batch`` forever. This resets ``retry_count`` to 0 and
        ``next_retry_at`` to ``now()`` so the retry worker re-attempts it on its next
        poll. Used to recover the 2,383 embeddings abandoned on the 2026-07-18 HTTP
        402 spend-cap hit, once the operator has raised the cap.

        Idempotent + throttle-friendly: it only touches rows that are STILL
        abandoned, so a row already re-queued (or since drained) is invisible to a
        second call. ``limit`` bounds the batch so a caller can throttle the flood of
        re-attempts (call repeatedly with a sleep between batches). Returns the number
        of rows reset this call — 0 means nothing left to re-queue.

        NOTE: run this ONLY after confirming the spend cap is raised (recent
        embedding successes, no fresh 402); otherwise the re-queued rows immediately
        re-fail. With the ProviderBillingError fix in place they will no longer be
        re-abandoned, but they will churn 402s until the cap clears.
        """
        result = await self._session.execute(
            text(
                "UPDATE embedding_pending "
                "SET retry_count = 0, next_retry_at = now(), last_attempted_at = now() "
                "WHERE pending_id IN ( "
                "    SELECT pending_id FROM embedding_pending "
                "    WHERE retry_count >= :max_retries "
                "    ORDER BY next_retry_at ASC "
                "    LIMIT :limit "
                "    FOR UPDATE SKIP LOCKED "
                ")"
            ),
            {"max_retries": max_retries, "limit": limit},
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
