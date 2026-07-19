"""EmbeddingRetryWorker — re-embeds failed section/chunk entries with backoff.

Periodically claims rows from ``embedding_pending``, calls the configured
EmbeddingClient, and on success writes to ``section_embeddings`` or
``chunk_embeddings`` then deletes the pending row.

Backoff: ``base_seconds * 2^retry_count``, capped at 3 600 s (1 hour).
Max retries: 5 — rows exceeding this limit are left in the table for manual
triage; they are never automatically deleted.

Error classification: transient failures (5xx / timeout / network / 429) keep
the exponential-backoff-retry behaviour above.  A *fatal* failure — the
embedding client raises :class:`ml_clients.errors.FatalError` for a bad-input HTTP
4xx (400/404/413/422) — will never succeed on retry, so the row is abandoned
immediately (``retry_count`` jumped to ``max_retries``) with a distinct
``embedding_retry_abandoned_permanent`` log instead of wasting all 5 attempts
over ~2 h.

Spend-cap / auth refusals (HTTP 402/401/403) are a THIRD class:
:class:`ml_clients.errors.ProviderBillingError`. These clear only when the operator
raises the DeepInfra spend cap, so they are backed off at a steady cadence WITHOUT
consuming the retry budget — the row never abandons and self-heals when the cap is
raised. (The 2026-07-18 incident abandoned 2,383 embeddings because HTTP 402 was
mis-classified as a fatal 4xx.) Use ``requeue_abandoned`` to recover rows abandoned
before this fix shipped.

Typical usage::

    worker = EmbeddingRetryWorker(nlp_sf, embedding_client, model_id="bge-large-en-v1.5", ...)
    stop = asyncio.Event()
    await worker.run_forever(stop)
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from ml_clients.errors import FatalError, ProviderBillingError  # type: ignore[import-not-found]

import common.ids  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.protocols import EmbeddingClient  # type: ignore[import-not-found]
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Default retry-attempt ceiling. Kept as a module-level constant for backward
# compatibility (existing tests import + assert against it). Production callers
# should pass ``max_retries=settings.embedding_retry_max_attempts`` to make the
# value operator-tunable per PLAN-0057 QA A-005.
_MAX_RETRIES: int = 5
_BACKOFF_BASE_SECONDS: float = 60.0
_MAX_BACKOFF_SECONDS: float = 3_600.0
_POLL_INTERVAL_SECONDS: float = 30.0
_BATCH_SIZE: int = 16
# Fixed backoff for a spend-cap / auth refusal (ProviderBillingError). Retried at a
# steady, low-frequency cadence (NOT exponential, and WITHOUT consuming the retry
# budget) so the row self-heals the moment the operator raises the cap while never
# hammering the provider with a flood of 402s. 5 min is a reasonable "cap likely
# still down" poll.
_BILLING_RETRY_BACKOFF_SECONDS: float = 300.0


class EmbeddingRetryWorker:
    """Background worker that retries failed embedding entries."""

    def __init__(
        self,
        nlp_session_factory: async_sessionmaker[AsyncSession],
        embedding_client: EmbeddingClient,
        model_id: str,
        instruction_prefix: str,
        poll_interval: float = _POLL_INTERVAL_SECONDS,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._nlp_sf = nlp_session_factory
        self._embedding_client = embedding_client
        self._model_id = model_id
        self._instruction_prefix = instruction_prefix
        self._poll_interval = poll_interval
        # PLAN-0057 QA A-005: previously hard-coded to ``_MAX_RETRIES`` here AND
        # as default kwarg in ``claim_batch`` / ``count_abandoned`` — drifting
        # the constant without updating the callers silently broke parity. Now
        # the worker carries the value and threads it through every call.
        self._max_retries = max_retries

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_once(self) -> int:
        """Process one batch of overdue pending entries.

        Returns the number of entries attempted (0 if nothing was due).
        """
        from nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending import (
            EmbeddingPendingRepository,
        )

        async with self._nlp_sf() as session:
            repo = EmbeddingPendingRepository(session)
            jobs = await repo.claim_batch(batch_size=_BATCH_SIZE, max_retries=self._max_retries)

        if not jobs:
            return 0

        for job in jobs:
            await self._process_job(job)

        return len(jobs)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        """Poll and retry embeddings until *stop_event* is set."""
        while not stop_event.is_set():
            try:
                count = await self.run_once()
                if count:
                    logger.info(  # type: ignore[no-any-return]
                        "embedding_retry_batch_done",
                        count=count,
                    )
            except Exception as exc:
                logger.warning(  # type: ignore[no-any-return]
                    "embedding_retry_poll_error",
                    error=str(exc),
                    exc_info=True,
                )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _process_job(self, job: Any) -> None:
        """Attempt one retry job; update the pending row on success or failure."""
        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-not-found]

        from nlp_pipeline.infrastructure.nlp_db.models import (
            ChunkEmbeddingModel,
            SectionEmbeddingModel,
        )
        from nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending import (
            EmbeddingPendingRepository,
        )

        # ── Attempt the embedding ─────────────────────────────────────────
        try:
            inp = EmbeddingInput(
                text=job.embedding_text,
                model_id=self._model_id,
                instruction_prefix=self._instruction_prefix,
            )
            outputs = await self._embedding_client.embed([inp])
            if not outputs:
                raise RuntimeError("Empty embedding response")
            vec = outputs[0].embedding
        except ProviderBillingError as exc:
            # Spend-cap / auth refusal (HTTP 402/401/403). NOT the row's fault and
            # clears only when the operator raises the cap. Back off WITHOUT
            # incrementing retry_count so the bounded 5-attempt budget is never spent
            # on a cap-down — the row keeps re-attempting and self-heals the moment the
            # cap is raised (the 2026-07-18 incident: 402 abandoned 2,383 embeddings
            # because it was mis-classified as a fatal 4xx). Distinct log so operators
            # can see cap pressure without it masquerading as a genuine failure.
            logger.warning(  # type: ignore[no-any-return]
                "embedding_retry_billing_deferred",
                pending_id=str(job.pending_id),
                doc_id=str(job.doc_id),
                retry_count=job.retry_count,
                reason="provider_billing",
                error=str(exc),
            )
            try:
                async with self._nlp_sf() as session:
                    repo = EmbeddingPendingRepository(session)
                    await repo.mark_failure(
                        job.pending_id,
                        backoff_seconds=_BILLING_RETRY_BACKOFF_SECONDS,
                        increment_retry=False,
                    )
                    await session.commit()
            except Exception as defer_exc:  # pragma: no cover — last resort
                logger.error(  # type: ignore[no-any-return]
                    "embedding_retry_billing_defer_mark_failed",
                    pending_id=str(job.pending_id),
                    error=str(defer_exc),
                )
            return
        except FatalError as exc:
            # Permanent failure — the embedding client raises FatalError only for
            # HTTP 4xx (non-429): bad/degenerate input (empty text, still >512
            # tokens after truncation), an unexpected vector dimension, or a
            # malformed response.  None of these can ever succeed on retry, so
            # burning all _MAX_RETRIES over ~2 h of exponential backoff is pure
            # waste.  Abandon the row immediately (retry_count jumps to
            # _max_retries) with a DISTINCT signal so operators can tell a fatal
            # 4xx apart from genuine transient exhaustion.
            #
            # Transient errors are NOT FatalError: 5xx / timeout / network →
            # RetryableError, and 429 → RateLimitError (a RetryableError
            # subclass).  They fall through to the backoff-retry branch below.
            logger.warning(  # type: ignore[no-any-return]
                "embedding_retry_abandoned_permanent",
                pending_id=str(job.pending_id),
                doc_id=str(job.doc_id),
                section_id=str(job.section_id) if job.section_id else None,
                chunk_id=str(job.chunk_id) if job.chunk_id else None,
                retry_count=job.retry_count,
                reason="fatal_4xx",
                error=str(exc),
            )
            # Fail-open: a DB error while abandoning must never crash the poll
            # loop — worst case the row keeps its old next_retry_at and is
            # retried once more later, which is still safe.
            try:
                async with self._nlp_sf() as session:
                    repo = EmbeddingPendingRepository(session)
                    await repo.mark_abandoned(
                        job.pending_id,
                        max_retries=self._max_retries,
                        error_detail=str(exc),
                    )
                    await session.commit()
            except Exception as mark_exc:  # pragma: no cover — last resort
                logger.error(  # type: ignore[no-any-return]
                    "embedding_retry_abandon_mark_failed",
                    pending_id=str(job.pending_id),
                    error=str(mark_exc),
                )
            return
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "embedding_retry_failed",
                pending_id=str(job.pending_id),
                retry_count=job.retry_count,
                error=str(exc),
            )
            backoff = min(_BACKOFF_BASE_SECONDS * (2.0**job.retry_count), _MAX_BACKOFF_SECONDS)
            async with self._nlp_sf() as session:
                repo = EmbeddingPendingRepository(session)
                await repo.mark_failure(job.pending_id, backoff_seconds=backoff)
                await session.commit()
            # PLAN-0057 Wave E-4: surface entries that have just hit the
            # _MAX_RETRIES ceiling and will therefore be silently skipped on
            # every subsequent ``claim_batch`` call.  Operators rely on this
            # log line to escalate to manual triage.
            if job.retry_count + 1 >= self._max_retries:
                logger.warning(  # type: ignore[no-any-return]
                    "embedding_retry_abandoned",
                    pending_id=str(job.pending_id),
                    doc_id=str(job.doc_id),
                    section_id=str(job.section_id) if job.section_id else None,
                    chunk_id=str(job.chunk_id) if job.chunk_id else None,
                    retry_count=job.retry_count + 1,
                    max_retries=self._max_retries,
                    final_error=str(exc),
                )
            return

        # ── Write the embedding and delete the pending row ────────────────
        try:
            async with self._nlp_sf() as session:
                if job.chunk_id is not None:
                    session.add(
                        ChunkEmbeddingModel(
                            embedding_id=common.ids.new_uuid7(),  # type: ignore[arg-type]
                            chunk_id=job.chunk_id,
                            embedding=vec,
                            model_id=self._model_id,
                        )
                    )
                elif job.section_id is not None:
                    session.add(
                        SectionEmbeddingModel(
                            embedding_id=common.ids.new_uuid7(),  # type: ignore[arg-type]
                            section_id=job.section_id,
                            embedding=vec,
                            model_id=self._model_id,
                        )
                    )
                repo = EmbeddingPendingRepository(session)
                await repo.mark_success(job.pending_id)
                await session.commit()

            logger.info(  # type: ignore[no-any-return]
                "embedding_retry_success",
                pending_id=str(job.pending_id),
                chunk_id=str(job.chunk_id) if job.chunk_id else None,
                section_id=str(job.section_id) if job.section_id else None,
            )
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "embedding_retry_write_failed",
                pending_id=str(job.pending_id),
                error=str(exc),
            )
            # PLAN-0057 QA DS-006 fix: without this fallback, write-side
            # failures left ``next_retry_at`` unchanged, so the next poll
            # re-claims the same row immediately and hot-loops on persistent
            # DB errors.  Bump retry_count + advance next_retry_at by 5 min
            # via a fresh session (the original session may be in an
            # unusable state after the commit failure).
            try:
                fallback_backoff = min(
                    _BACKOFF_BASE_SECONDS * (2.0**job.retry_count) + 240.0,
                    _MAX_BACKOFF_SECONDS,
                )
                async with self._nlp_sf() as recovery_session:
                    recovery_repo = EmbeddingPendingRepository(recovery_session)
                    await recovery_repo.mark_failure(job.pending_id, backoff_seconds=fallback_backoff)
                    await recovery_session.commit()
            except Exception as recovery_exc:  # pragma: no cover — last resort
                logger.error(  # type: ignore[no-any-return]
                    "embedding_retry_fallback_mark_failure_failed",
                    pending_id=str(job.pending_id),
                    error=str(recovery_exc),
                )
