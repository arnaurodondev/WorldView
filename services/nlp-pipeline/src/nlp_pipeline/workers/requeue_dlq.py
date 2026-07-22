"""Admin one-shot: re-queue dead-lettered articles back onto their topic (402-replay recovery).

Background
----------
When the DeepInfra spend cap is hit, article extraction fails with HTTP 402
``Payment Required``. Before the 402-replay hardening, the article-processing
consumer routed that ``ProviderBillingError`` through its generic transient branch,
which counts against ``max_retries`` and DEAD-LETTERS the article after exhaustion —
the 2026-07-18 incident lost 693 articles to ``nlp_db.dead_letter_queue`` this way.

The consumer now DEFERS a billing refusal without consuming the retry budget and never
dead-letters, so this can NOT recur. But articles already sitting in the DLQ from a
prior cap-down still need a one-time replay. This script is that one command.

What it does
------------
Requeues open (``status='failed'``) DLQ rows in throttled batches: for each row it
inserts a fresh PENDING outbox event carrying the row's ORIGINAL Avro payload + topic
(the outbox dispatcher republishes it to the input topic the article consumer reads)
and flips the DLQ row to ``resolved``. This is the bulk form of the proven
``POST /admin/dlq/{id}/retry`` single-entry path.

By default it targets only spend-cap-caused entries (``--error-contains 402``) so a
replay after funding does not also re-drive genuinely-poison messages (malformed
payloads etc.). Pass ``--all`` to requeue every open entry regardless of error.

Idempotent: only STILL-open rows are touched and each is marked ``resolved`` in the
same transaction as its requeue, so a re-run (or a concurrent consumer draining the
republished events) is a no-op. Consumption is idempotent too (ValkeyDedupMixin +
deterministic IDs), so a redelivered payload cannot create duplicates.

Safety
------
Run ONLY after confirming the spend cap is raised — recent extractions are succeeding
and no fresh HTTP 402. Otherwise the requeued articles just fail again (they will
billing-defer, not re-dead-letter, but it is wasted effort).

Defaults to DRY-RUN (reports the open count and exits without mutating). Pass
``--execute`` to actually requeue.

Usage::

    # dry-run — how many spend-cap-caused DLQ entries are open?
    python -m nlp_pipeline.workers.requeue_dlq

    # execute — requeue the 402-caused backlog in batches of 200
    python -m nlp_pipeline.workers.requeue_dlq --execute --batch-size 200 --sleep 2.0

    # execute — requeue EVERY open DLQ entry (not just billing-caused)
    python -m nlp_pipeline.workers.requeue_dlq --execute --all
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

#: Default ``error_detail`` substring — targets the spend-cap backlog. The article
#: consumer stamps ``str(ProviderBillingError)`` (which includes the HTTP status) into
#: ``error_detail`` when it dead-letters, so "402" selects the billing-caused rows.
_DEFAULT_ERROR_CONTAINS = "402"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-queue dead-lettered articles (402-replay recovery).")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually requeue rows. Without this flag the script is a dry-run (report only).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Requeue EVERY open DLQ entry, not just spend-cap-caused ones (ignores --error-contains).",
    )
    parser.add_argument(
        "--error-contains",
        type=str,
        default=_DEFAULT_ERROR_CONTAINS,
        help=(
            "Case-insensitive substring the DLQ error_detail must contain to be requeued. "
            f"Default {_DEFAULT_ERROR_CONTAINS!r} (spend-cap 402s). Ignored when --all is set."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Rows requeued per batch (throttle knob). Default 200.",
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
    from nlp_pipeline.infrastructure.nlp_db.repositories.dlq import DLQRepository
    from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="nlp-pipeline-requeue-dlq",
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("nlp_pipeline.requeue_dlq")  # type: ignore[no-any-return]

    # ``--all`` overrides the filter (None → no error_detail predicate).
    error_contains = None if args.all else args.error_contains
    nlp_engine, _read_engine, nlp_sf, _read_sf = _build_nlp_factories(settings)

    try:
        async with nlp_sf() as session:
            repo = DLQRepository(session)
            open_count = await repo.count_open(error_contains=error_contains)

        log.info(
            "requeue_dlq_start",
            open_count=open_count,
            error_contains=error_contains,
            requeue_all=args.all,
            execute=args.execute,
            batch_size=args.batch_size,
        )

        if not args.execute:
            log.warning(
                "requeue_dlq_dry_run",
                open_count=open_count,
                error_contains=error_contains,
                note="re-run with --execute to requeue these entries (confirm spend cap is raised first)",
            )
            return 0

        total_requeued = 0
        for _ in range(args.max_batches):
            async with nlp_sf() as session:
                repo = DLQRepository(session)
                requeued = await repo.requeue_open_batch(error_contains=error_contains, limit=args.batch_size)
                await session.commit()
            if requeued == 0:
                break
            total_requeued += requeued
            log.info("requeue_dlq_batch", requeued=requeued, total_requeued=total_requeued)
            if args.sleep > 0:
                await asyncio.sleep(args.sleep)

        log.info("requeue_dlq_complete", total_requeued=total_requeued)
        return 0
    finally:
        await nlp_engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
