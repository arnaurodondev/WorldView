"""Operational helper — enqueue a brokerage re-sync for every active connection.

PLAN-0046 follow-up / F-018 (QA 2026-04-28).

Why this exists:
    Adding the new ``transactions.amount`` column (Alembic 0009) does not
    backfill historical rows. The DIVIDEND values flow only on the next
    sync cycle. Operators need a one-shot way to "kick" every active
    SnapTrade connection so the next cycle re-fetches activities (with
    ``amount`` captured this time) and the user sees correct dividend
    totals immediately.

What it does:
    Iterates ``brokerage_connections`` rows where ``status IN
    ('active', 'error')``. For each one, it nudges the cursor so the
    in-place ``BrokerageTransactionSyncWorker`` picks the connection up
    on its next cycle. Concretely we ``UPDATE brokerage_connections SET
    last_synced_at = NULL WHERE id = :id`` — that resets the resume
    cursor and the worker will replay the full activity window on its
    next pass.

    We deliberately do NOT call SnapTrade synchronously here. Doing so
    would require holding the encryption key in this short-lived script
    and would block on the SDK's synchronous I/O for many seconds per
    connection. Letting the dedicated long-running worker do the actual
    fetch keeps the operational surface area small.

Idempotency:
    Re-running the script just zeroes the cursor again. The worker is
    already idempotent (transactions are upserted by SnapTrade activity
    id), so a duplicate kick produces zero new rows.

Usage:
    # Dry-run — print what would change, mutate nothing.
    python -m portfolio.scripts.trigger_brokerage_resync --dry-run

    # Live — reset cursors so the worker re-syncs on its next cycle.
    python -m portfolio.scripts.trigger_brokerage_resync

Note:
    This script does NOT issue any network call. It only mutates the
    local DB cursor. The actual SnapTrade re-fetch happens in
    ``BrokerageTransactionSyncWorker`` on its next 4-hour cycle.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

import structlog
from portfolio.config import Settings
from portfolio.infrastructure.db.session import _build_factories
from sqlalchemy import text

from observability import configure_logging  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)


@dataclass
class ResyncReport:
    """Summary of what the script did / would do."""

    connections_eligible: int
    connections_updated: int
    dry_run: bool


async def _run(settings: Settings, *, dry_run: bool) -> ResyncReport:
    """Reset the resume cursor on every active/error connection."""
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    async with write_factory() as session:
        # Count first so the dry-run output reports the same number we
        # would mutate. ``status IN ('active', 'error')`` matches the
        # filter the sync worker uses.
        count_result = await session.execute(
            text(
                """
                SELECT COUNT(*) FROM brokerage_connections
                WHERE status IN ('active', 'error')
                """,
            ),
        )
        eligible = int(count_result.scalar() or 0)

        if eligible == 0:
            logger.info("trigger_resync_no_eligible_connections")
            return ResyncReport(0, 0, dry_run)

        if dry_run:
            logger.info(
                "trigger_resync_dry_run",
                connections_eligible=eligible,
                action="would zero last_synced_at + last_sync_cursor",
            )
            return ResyncReport(eligible, 0, dry_run)

        # Live — reset both the timestamp cursor and the explicit
        # ``last_sync_cursor`` so the worker replays from the beginning
        # of its lookback window. Both fields are nullable so this is
        # safe.
        update_result = await session.execute(
            text(
                """
                UPDATE brokerage_connections
                SET last_synced_at = NULL,
                    last_sync_cursor = NULL,
                    updated_at = NOW()
                WHERE status IN ('active', 'error')
                """,
            ),
        )
        await session.commit()
        # ``rowcount`` is the authoritative count of affected rows.
        updated = int(update_result.rowcount or 0)
        logger.info("trigger_resync_complete", updated=updated)
        return ResyncReport(eligible, updated, dry_run)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset cursors so BrokerageTransactionSyncWorker re-syncs on its next cycle.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report would-be updates without mutating anything.",
    )
    return parser.parse_args(argv)


async def amain(argv: list[str]) -> int:
    args = _parse_args(argv)
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="portfolio-trigger-brokerage-resync",
        level=settings.log_level,
        json=settings.log_json,
    )
    report = await _run(settings, dry_run=args.dry_run)
    logger.info(
        "trigger_resync_report",
        connections_eligible=report.connections_eligible,
        connections_updated=report.connections_updated,
        dry_run=report.dry_run,
    )
    # Non-zero exit only on a configuration/DB failure (caught by
    # asyncio runtime as an exception). Zero rows updated in dry-run is
    # still a successful run.
    return 0


def main() -> None:
    sys.exit(asyncio.run(amain(sys.argv[1:])))


if __name__ == "__main__":
    main()
