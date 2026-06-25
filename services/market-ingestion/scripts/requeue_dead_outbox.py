#!/usr/bin/env python3
"""Operator one-shot: requeue dead-lettered outbox rows back to ``pending``.

WHY THIS SCRIPT EXISTS (BUG-5):
  market-ingestion's outbox dispatcher moves rows that exhaust ``max_attempts``
  to ``status='dead'``. ``claim_batch`` only selects ``status IN
  ('pending','retry')``, so once a row is dead-lettered NOTHING can re-dispatch
  it. The live ``ingestion_db`` had 24,163 ``status='dead'``
  ``market.dataset.fetched`` rows permanently stranded.

  This script is the SAFE, OPERATOR-INVOKABLE recovery path. It moves ``dead``
  rows back to ``pending`` (clearing the lease, resetting ``next_attempt_at`` and
  the attempt counter) so the running dispatcher re-claims and re-publishes them.

SAFETY MODEL:
  * ``--dry-run`` (DEFAULT) only COUNTS — it never mutates. Pass ``--apply`` to
    actually requeue.
  * BOUNDED: you MUST pass at least one of ``--topic``, ``--older-than-days``, or
    ``--ids``. An unbounded requeue of the whole dead pool is refused.
  * Idempotent: only rows currently in ``dead`` are touched.

USAGE (run inside the market-ingestion image / venv):
  cd services/market-ingestion
  python scripts/requeue_dead_outbox.py --dry-run
  python scripts/requeue_dead_outbox.py --dry-run --topic market.dataset.fetched
  python scripts/requeue_dead_outbox.py --apply --topic market.dataset.fetched
  python scripts/requeue_dead_outbox.py --apply --older-than-days 7

ENV: standard MARKET_INGESTION_* settings (DATABASE_URL).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from market_ingestion.config import Settings
from market_ingestion.infrastructure.db.repositories.outbox_repository import SqlaOutboxRepository
from market_ingestion.infrastructure.db.session import _build_factories

log = structlog.get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Requeue dead-lettered market-ingestion outbox rows.")
    parser.add_argument("--topic", default=None, help="Only requeue rows for this Kafka topic.")
    parser.add_argument(
        "--older-than-days",
        type=float,
        default=None,
        help="Only requeue rows created at least this many days ago.",
    )
    parser.add_argument("--ids", nargs="*", default=None, help="Explicit allow-list of outbox row ids.")
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

    settings = Settings()  # type: ignore[call-arg]
    write_factory, read_factory = _build_factories(settings)

    async with write_factory() as write_session, read_factory() as read_session:
        repo = SqlaOutboxRepository(write_session, read_session)
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

        if args.ids is None and args.topic is None and older_than is None:
            log.error("requeue_dead_outbox.unbounded_refused", note="pass --topic/--older-than-days/--ids")
            return 2

        moved = await repo.requeue_dead_to_pending(
            ids=args.ids,
            topic=args.topic,
            older_than=older_than,
        )
        await write_session.commit()
        log.info(
            "requeue_dead_outbox.applied",
            requeued=moved,
            matched=count,
            topic=args.topic,
            older_than=older_than.isoformat() if older_than else None,
        )
        return 0


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
