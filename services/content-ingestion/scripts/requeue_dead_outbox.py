#!/usr/bin/env python3
"""Operator one-shot: requeue dead-lettered outbox rows back to ``pending``.

WHY THIS SCRIPT EXISTS (BUG-5 / BUG-6):
  content-ingestion's outbox dispatcher moves rows that exhaust ``max_attempts``
  to ``status='dead_letter'``. ``fetch_pending`` only selects ``pending`` /
  ``processing`` rows, so once a row is dead-lettered NOTHING can re-dispatch it.
  The live ``content_ingestion_db`` had 2,259 ``dead_letter`` rows: 1,653
  ``market.prediction.v1`` + 606 ``content.article.raw.v1``.

  This script is the SAFE, OPERATOR-INVOKABLE recovery path. It moves
  ``dead_letter`` rows back to ``pending`` (clearing the lease, resetting
  ``attempts``) so the running dispatcher re-claims and re-publishes them.

  IMPORTANT (BUG-6): the 1,653 ``market.prediction.v1`` dead-letters are
  suspected to stem from an Avro/Schema-Registry serialization drift, NOT a
  transient blip. Requeueing only re-attempts DELIVERY — if the underlying drift
  is real, those rows will simply re-dead-letter. Run the contract test
  (``tests/contract/test_outbox_avro_contract.py``) and fix the producer/schema
  FIRST, then requeue the prediction topic. Article rows (transient
  wedged-producer timeouts) are safe to requeue directly.

SAFETY MODEL:
  * ``--dry-run`` (DEFAULT) only COUNTS — it never mutates. Pass ``--apply``.
  * BOUNDED: you MUST pass at least one of ``--topic``, ``--older-than-days``, or
    ``--ids``. An unbounded requeue is refused.
  * Idempotent: only rows currently in ``dead_letter`` are touched.

USAGE (run inside the content-ingestion image / venv):
  cd services/content-ingestion
  python scripts/requeue_dead_outbox.py --dry-run
  python scripts/requeue_dead_outbox.py --dry-run --topic content.article.raw.v1
  python scripts/requeue_dead_outbox.py --apply --topic content.article.raw.v1
  # only AFTER fixing the prediction schema drift:
  python scripts/requeue_dead_outbox.py --apply --topic market.prediction.v1

ENV: standard content-ingestion settings (DB_URL).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from content_ingestion.config import Settings
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.db.session import _build_factories

log = structlog.get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Requeue dead-lettered content-ingestion outbox rows.")
    parser.add_argument("--topic", default=None, help="Only requeue rows for this Kafka topic.")
    parser.add_argument(
        "--older-than-days",
        type=float,
        default=None,
        help="Only requeue rows created at least this many days ago.",
    )
    parser.add_argument("--ids", nargs="*", default=None, help="Explicit allow-list of outbox row ids (UUIDs).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="(default) Only count matching dead rows; do not mutate.",
    )
    mode.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Actually requeue the matching dead rows.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    older_than: datetime | None = None
    if args.older_than_days is not None:
        older_than = datetime.now(tz=UTC) - timedelta(days=args.older_than_days)

    ids = [UUID(i) for i in args.ids] if args.ids else None

    settings = Settings()  # type: ignore[call-arg]
    write_engine, read_engine, write_factory, _read_factory = _build_factories(settings)

    try:
        async with write_factory() as session:
            repo = OutboxRepository(session)
            count = await repo.count_dead(topic=args.topic, older_than=older_than)

            if args.dry_run:
                log.info(
                    "requeue_dead_outbox.dry_run",
                    matching=count,
                    topic=args.topic,
                    older_than=older_than.isoformat() if older_than else None,
                    ids=args.ids,
                    note="no rows mutated; pass --apply to requeue",
                )
                return 0

            if ids is None and args.topic is None and older_than is None:
                log.error("requeue_dead_outbox.unbounded_refused", note="pass --topic/--older-than-days/--ids")
                return 2

            moved = await repo.requeue_dead_to_pending(ids=ids, topic=args.topic, older_than=older_than)
            await session.commit()
            log.info(
                "requeue_dead_outbox.applied",
                requeued=moved,
                matched=count,
                topic=args.topic,
                older_than=older_than.isoformat() if older_than else None,
            )
            return 0
    finally:
        await write_engine.dispose()
        if read_engine is not write_engine:
            await read_engine.dispose()


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
