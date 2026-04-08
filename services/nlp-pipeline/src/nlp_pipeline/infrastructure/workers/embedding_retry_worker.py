"""EmbeddingRetryWorker — re-embeds failed section/chunk entries with backoff.

Periodically claims rows from ``embedding_pending``, calls the configured
EmbeddingClient, and on success writes to ``section_embeddings`` or
``chunk_embeddings`` then deletes the pending row.

Backoff: ``base_seconds * 2^retry_count``, capped at 3 600 s (1 hour).
Max retries: 5 — rows exceeding this limit are left in the table for manual
triage; they are never automatically deleted.

Typical usage::

    worker = EmbeddingRetryWorker(nlp_sf, embedding_client, model_id="bge-large-en-v1.5", ...)
    stop = asyncio.Event()
    await worker.run_forever(stop)
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import common.ids  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.protocols import EmbeddingClient  # type: ignore[import-not-found]
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

_MAX_RETRIES: int = 5
_BACKOFF_BASE_SECONDS: float = 60.0
_MAX_BACKOFF_SECONDS: float = 3_600.0
_POLL_INTERVAL_SECONDS: float = 30.0
_BATCH_SIZE: int = 16


class EmbeddingRetryWorker:
    """Background worker that retries failed embedding entries."""

    def __init__(
        self,
        nlp_session_factory: async_sessionmaker[AsyncSession],
        embedding_client: EmbeddingClient,
        model_id: str,
        instruction_prefix: str,
        poll_interval: float = _POLL_INTERVAL_SECONDS,
    ) -> None:
        self._nlp_sf = nlp_session_factory
        self._embedding_client = embedding_client
        self._model_id = model_id
        self._instruction_prefix = instruction_prefix
        self._poll_interval = poll_interval

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
            jobs = await repo.claim_batch(batch_size=_BATCH_SIZE, max_retries=_MAX_RETRIES)

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
