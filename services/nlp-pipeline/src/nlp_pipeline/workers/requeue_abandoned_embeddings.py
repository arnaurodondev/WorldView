"""Admin one-shot: re-queue abandoned ``embedding_pending`` rows (2026-07-18 spend-cap recovery).

Background
----------
On 2026-07-18 the DeepInfra spend cap was hit. The embedding adapter returned HTTP
402 ``Payment Required``, which the adapter mis-classified as a fatal 4xx, so the
``EmbeddingRetryWorker`` abandoned the affected rows (``retry_count >= max_retries``).
``claim_batch`` skips abandoned rows forever, so ~2,383 embeddings became permanently
unsearchable. The adapter now raises :class:`ml_clients.errors.ProviderBillingError`
(retryable, no budget consumption) so this can never recur — but rows abandoned
BEFORE that fix shipped still need a one-time reset.

What it does
------------
Resets ``retry_count = 0`` and ``next_retry_at = now()`` for abandoned rows in
throttled batches, so the running ``EmbeddingRetryWorker`` re-attempts them on its
next poll. Idempotent: only STILL-abandoned rows are touched, so a re-run (or a
concurrent worker draining them) is a no-op.

Safety
------
Run ONLY after confirming the spend cap is raised — recent embedding successes are
flowing and no fresh HTTP 402. Otherwise the re-queued rows immediately re-fail
(they will churn 402s at the billing cadence, not abandon, but it is wasted effort).

Defaults to DRY-RUN (reports the abandoned count and exits without mutating). Pass
``--execute`` to actually re-queue.

Usage::

    # dry-run — just report how many rows are abandoned
    python -m nlp_pipeline.workers.requeue_abandoned_embeddings

    # execute — reset in batches of 200 with a 2s pause between batches
    python -m nlp_pipeline.workers.requeue_abandoned_embeddings --execute --batch-size 200 --sleep 2.0
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-queue abandoned embedding_pending rows.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually re-queue rows. Without this flag the script is a dry-run (report only).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Rows reset per batch (throttle knob). Default 200.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        help="Seconds to sleep between batches (throttle knob). Default 2.0.",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=1000,
        help="Safety ceiling on batch iterations. Default 1000.",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending import (
        EmbeddingPendingRepository,
    )
    from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="nlp-pipeline-requeue-abandoned-embeddings",
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("nlp_pipeline.requeue_abandoned_embeddings")  # type: ignore[no-any-return]

    max_retries = settings.embedding_retry_max_attempts
    nlp_engine, _read_engine, nlp_sf, _read_sf = _build_nlp_factories(settings)

    try:
        async with nlp_sf() as session:
            repo = EmbeddingPendingRepository(session)
            abandoned = await repo.count_abandoned(max_retries=max_retries)

        log.info(
            "requeue_abandoned_start",
            abandoned=abandoned,
            max_retries=max_retries,
            execute=args.execute,
            batch_size=args.batch_size,
        )

        if not args.execute:
            log.warning(
                "requeue_abandoned_dry_run",
                abandoned=abandoned,
                note="re-run with --execute to reset these rows (confirm spend cap is raised first)",
            )
            return 0

        total_reset = 0
        for _ in range(args.max_batches):
            async with nlp_sf() as session:
                repo = EmbeddingPendingRepository(session)
                reset = await repo.requeue_abandoned(max_retries=max_retries, limit=args.batch_size)
                await session.commit()
            if reset == 0:
                break
            total_reset += reset
            log.info("requeue_abandoned_batch", reset=reset, total_reset=total_reset)
            if args.sleep > 0:
                await asyncio.sleep(args.sleep)

        log.info("requeue_abandoned_complete", total_reset=total_reset)
        return 0
    finally:
        await nlp_engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
