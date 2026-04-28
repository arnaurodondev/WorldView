"""Operational recovery script for PLAN-0046 / BP-264 — holdings replay drift.

Background:
    Before PLAN-0046, ``RecordTransactionUseCase`` mutated ``holdings.quantity``
    via ``apply_delta`` on every transaction. The SnapTrade adapter could return
    the same activity twice (legacy + per-account fallback paths emit different
    IDs for the same trade), causing ``holdings.quantity`` to inflate by 8-10x.
    See ``docs/audits/2026-04-28-qa-plan-0044-followup-report.md`` (F-001).

What this script does:
    1. Lists every portfolio that has at least one ``brokerage_connection`` row.
    2. (mutate mode only) Zero-outs ``holdings.quantity`` and ``average_cost``
       for every holding belonging to those portfolios — the next sync cycle
       will repopulate them from the broker's position snapshot, which is now
       authoritative (see ``UpsertHoldingsFromSnapshotUseCase``).
    3. Detects probable duplicate transactions (same ``portfolio_id``,
       ``instrument_id``, ``trade_date`` (date), ``quantity``, ``price``) and
       reports them. Duplicates are NOT auto-deleted — the operator decides
       based on the report whether to clean them up.

Idempotency:
    - Safe to re-run. After a successful zero-out + brokerage sync, holdings
      will already match the broker; running again zeroes them out a second
      time and the next sync cycle restores them. The only cost of re-running
      is one extra sync round-trip.
    - The duplicate-detection report is read-only and always idempotent.

Usage:
    # Dry run — print what would change, mutate nothing.
    python -m portfolio.scripts.repair_holdings_after_replay_drift --dry-run

    # Live run — zero-out holdings; subsequent sync repopulates from broker.
    python -m portfolio.scripts.repair_holdings_after_replay_drift

Environment:
    Loads the same ``Settings`` as the API server (database URL, etc.).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import structlog
from portfolio.config import Settings
from portfolio.infrastructure.db.session import _build_factories
from sqlalchemy import text

from observability import configure_logging  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)


@dataclass
class RepairReport:
    """Summary of what the script did / would do (for both dry-run and live runs)."""

    portfolios_with_brokerage: int
    holdings_zeroed_out: int
    duplicate_transaction_groups: int
    duplicate_transaction_rows: int


async def _run(settings: Settings, *, dry_run: bool) -> RepairReport:
    """Execute the repair flow against the configured database."""
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    portfolios_with_brokerage = 0
    holdings_zeroed = 0
    dup_groups = 0
    dup_rows = 0

    async with write_factory() as session:
        # 1. Find portfolios with any brokerage connection.
        result = await session.execute(
            text(
                """
                SELECT DISTINCT bc.portfolio_id
                FROM brokerage_connections bc
                """,
            ),
        )
        affected_portfolio_ids: list[Any] = [row[0] for row in result.fetchall()]
        portfolios_with_brokerage = len(affected_portfolio_ids)

        if portfolios_with_brokerage == 0:
            logger.info("no_brokerage_portfolios_found")
            return RepairReport(0, 0, 0, 0)

        # 2. Zero-out holdings (or report intent).
        count_result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM holdings
                WHERE portfolio_id = ANY(:pids) AND quantity <> 0
                """,
            ),
            {"pids": affected_portfolio_ids},
        )
        holdings_zeroed = int(count_result.scalar() or 0)

        if dry_run:
            logger.info(
                "dry_run_would_zero_out_holdings",
                portfolios=portfolios_with_brokerage,
                holdings=holdings_zeroed,
            )
        else:
            await session.execute(
                text(
                    """
                    UPDATE holdings
                    SET quantity = :zero, average_cost = :zero
                    WHERE portfolio_id = ANY(:pids)
                    """,
                ),
                {"pids": affected_portfolio_ids, "zero": Decimal(0)},
            )
            await session.commit()
            logger.info(
                "holdings_zeroed",
                portfolios=portfolios_with_brokerage,
                holdings=holdings_zeroed,
            )

        # 3. Duplicate-transactions detection (always read-only).
        dup_result = await session.execute(
            text(
                """
                SELECT portfolio_id,
                       instrument_id,
                       DATE(executed_at) AS trade_date,
                       quantity,
                       price,
                       COUNT(*) AS dup_count
                FROM transactions
                WHERE portfolio_id = ANY(:pids)
                GROUP BY portfolio_id, instrument_id, DATE(executed_at), quantity, price
                HAVING COUNT(*) > 1
                """,
            ),
            {"pids": affected_portfolio_ids},
        )
        for row in dup_result.fetchall():
            dup_groups += 1
            dup_rows += int(row.dup_count)
            logger.info(
                "duplicate_transaction_group",
                portfolio_id=str(row.portfolio_id),
                instrument_id=str(row.instrument_id),
                trade_date=str(row.trade_date),
                quantity=str(row.quantity),
                price=str(row.price),
                dup_count=int(row.dup_count),
            )

    return RepairReport(
        portfolios_with_brokerage=portfolios_with_brokerage,
        holdings_zeroed_out=holdings_zeroed,
        duplicate_transaction_groups=dup_groups,
        duplicate_transaction_rows=dup_rows,
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair holdings drift caused by transaction-replay (BP-264).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without mutating anything.",
    )
    return parser.parse_args(argv)


async def amain(argv: list[str]) -> int:
    args = _parse_args(argv)
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="portfolio-repair-holdings-drift",
        level=settings.log_level,
        json=settings.log_json,
    )

    report = await _run(settings, dry_run=args.dry_run)

    logger.info(
        "repair_complete",
        dry_run=args.dry_run,
        portfolios_with_brokerage=report.portfolios_with_brokerage,
        holdings_zeroed_out=report.holdings_zeroed_out,
        duplicate_transaction_groups=report.duplicate_transaction_groups,
        duplicate_transaction_rows=report.duplicate_transaction_rows,
    )

    # Exit non-zero only on fatal error — duplicate detection is informational.
    return 0


def main() -> None:
    sys.exit(asyncio.run(amain(sys.argv[1:])))


if __name__ == "__main__":
    main()
