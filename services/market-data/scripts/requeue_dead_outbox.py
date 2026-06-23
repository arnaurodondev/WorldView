#!/usr/bin/env python3
"""Operator one-shot: requeue dead-lettered outbox rows back to ``pending``.

WHY THIS SCRIPT EXISTS (BUG-5):
  market-data's outbox dispatcher moves rows that exhaust ``max_attempts`` to
  ``status='dead_letter'``. ``fetch_pending`` only ever selects ``pending`` rows,
  so once a row is dead-lettered NOTHING can re-dispatch it — the 44 lost
  ``market.instrument.*`` events from the 2026-06-17 broker blip were stranded
  forever (they drive S1 InstrumentRef + S7 canonical-entity creation).

  This script is the SAFE, OPERATOR-INVOKABLE recovery path. It moves
  ``dead_letter`` rows back to ``pending`` (clearing the lease and resetting the
  attempt counter) so the running dispatcher re-claims and re-publishes them.

  Pair this with the BUG-4 fix (``max_attempts`` 5 → 20): the higher budget
  prevents future dead-lettering from transient blips; this script recovers the
  rows that already dead-lettered under the old budget.

SAFETY MODEL:
  * ``--dry-run`` (DEFAULT) only COUNTS — it never mutates. You must pass
    ``--apply`` to actually requeue.
  * The requeue is BOUNDED: you MUST pass at least one of ``--topic``,
    ``--older-than-days``, or ``--ids``. An unbounded requeue of the whole dead
    pool is refused by the repository.
  * Idempotent: only rows currently in ``dead_letter`` are touched, so re-running
    is a no-op once rows have moved to ``pending``/``delivered``.

USAGE (run inside the market-data image / venv):
  cd services/market-data
  # 1. See how many dead rows exist (dry-run, no mutation):
  python scripts/requeue_dead_outbox.py --dry-run
  python scripts/requeue_dead_outbox.py --dry-run --topic market.instrument.created
  # 2. Requeue a bounded set (requires --apply):
  python scripts/requeue_dead_outbox.py --apply --topic market.instrument.created
  python scripts/requeue_dead_outbox.py --apply --older-than-days 1
  python scripts/requeue_dead_outbox.py --apply --ids <uuid> <uuid> ...

ENV: standard MARKET_DATA_* settings (DATABASE_URL via MARKET_DATA_DATABASE_URL).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from market_data.config import Settings
from market_data.infrastructure.db.repositories.outbox_event_repo import PgOutboxEventRepository
from market_data.infrastructure.db.session import build_session_factory, build_write_engine

log = structlog.get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Requeue dead-lettered market-data outbox rows.")
    parser.add_argument("--topic", default=None, help="Only requeue rows for this Kafka topic.")
    parser.add_argument(
        "--older-than-days",
        type=float,
        default=None,
        help="Only requeue rows created at least this many days ago.",
    )
    parser.add_argument(
        "--ids",
        nargs="*",
        default=None,
        help="Explicit allow-list of outbox row ids to requeue.",
    )
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
    engine = build_write_engine(settings)
    factory = build_session_factory(engine)

    try:
        async with factory() as session:
            repo = PgOutboxEventRepository(session)
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
        await engine.dispose()


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
