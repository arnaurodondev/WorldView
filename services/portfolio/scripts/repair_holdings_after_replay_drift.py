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

F-201 guard (QA iter-2):
    Iter-1 ran this script against the live stack and zeroed every Demo
    holding. The SnapTrade SANDBOX returned ``activity_count=0`` on the
    follow-up resync, so the broker never repopulated holdings, leaving
    the user with a $178k equity curve over $0 of positions.

    The guard added here refuses to zero a portfolio's holdings unless we
    have evidence the broker will actually re-populate them. Concretely,
    for each candidate portfolio, the connection's ``last_synced_at`` must
    be **within the last 24 hours** AND the portfolio must currently have
    at least one ``transactions`` row (proxy for "the broker is actively
    feeding us data"). If neither is true the portfolio is skipped with a
    clear warning. Operators can override with ``--force``.

    F-204 follow-up: when we DO zero a portfolio (only with --force after
    iter-2), we also DELETE today's ``portfolio_value_snapshots`` row so
    the next snapshot run recomputes from the new (zeroed) state instead
    of the user seeing yesterday's number against today's empty positions.

Idempotency:
    - Safe to re-run. After a successful zero-out + brokerage sync, holdings
      will already match the broker; running again zeroes them out a second
      time and the next sync cycle restores them. The only cost of re-running
      is one extra sync round-trip.
    - The duplicate-detection report is read-only and always idempotent.

Usage:
    # Dry run — print what would change, mutate nothing.
    python -m portfolio.scripts.repair_holdings_after_replay_drift --dry-run

    # Live run — zero-out holdings only for portfolios that pass the guard.
    python -m portfolio.scripts.repair_holdings_after_replay_drift

    # Override the guard (operator accepts the risk of orphaning holdings).
    python -m portfolio.scripts.repair_holdings_after_replay_drift --force

Environment:
    Loads the same ``Settings`` as the API server (database URL, etc.).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from portfolio.config import Settings
from portfolio.infrastructure.db.session import _build_factories
from sqlalchemy import text

from observability import configure_logging  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)

# F-201 guard — a connection's last_synced_at must be within this window for
# us to consider the broker "actively feeding us data". 24h is generous: the
# brokerage sync worker runs every 4h, so a connection that hasn't synced in a
# day means either the worker is broken or the broker is returning nothing.
# Either way zeroing the holdings will orphan the portfolio.
_FRESH_SYNC_WINDOW = timedelta(hours=24)


@dataclass
class RepairReport:
    """Summary of what the script did / would do (for both dry-run and live runs)."""

    portfolios_with_brokerage: int
    holdings_zeroed_out: int
    duplicate_transaction_groups: int
    duplicate_transaction_rows: int
    # F-201: portfolios skipped because the guard fired (stale sync / no
    # transactions). Not an error — operator can use --force to override.
    portfolios_skipped_by_guard: int = 0


async def _gather_eligible_portfolios(
    session: Any,  # AsyncSession; typed as Any to avoid SQLAlchemy import gymnastics in the script
    *,
    force: bool,
) -> tuple[list[Any], list[Any]]:
    """Split the brokerage-connected portfolios into (eligible, skipped) lists.

    Eligible portfolios pass the F-201 guard:
      * connection has ``last_synced_at`` within the last 24h, AND
      * the portfolio has at least one transaction row.

    With ``force=True`` everything is eligible — operator overrides the guard.
    Returns ``(eligible_ids, skipped_ids)`` where each is a list of portfolio
    UUIDs. The caller logs/processes them.
    """
    result = await session.execute(
        text(
            """
            SELECT DISTINCT bc.portfolio_id, bc.last_synced_at
            FROM brokerage_connections bc
            """,
        ),
    )
    rows = result.fetchall()
    if not rows:
        return [], []

    if force:
        return [r[0] for r in rows], []

    now_utc = datetime.now(tz=UTC)
    eligible: list[Any] = []
    skipped: list[Any] = []
    for portfolio_id, last_synced_at in rows:
        # last_synced_at None → broker never returned anything; skip.
        if last_synced_at is None:
            logger.warning(
                "repair_skip_no_sync_history",
                portfolio_id=str(portfolio_id),
                reason="last_synced_at IS NULL",
            )
            skipped.append(portfolio_id)
            continue

        # Stale sync (>24h) → the worker isn't actively feeding us; skip.
        if now_utc - last_synced_at > _FRESH_SYNC_WINDOW:
            logger.warning(
                "repair_skip_stale_sync",
                portfolio_id=str(portfolio_id),
                last_synced_at=last_synced_at.isoformat(),
                reason=f"last sync older than {_FRESH_SYNC_WINDOW}",
            )
            skipped.append(portfolio_id)
            continue

        # No transactions for this portfolio → broker hasn't given us anything
        # to record. Zeroing would orphan the holdings (per F-201 incident).
        # We use ``transactions`` as the proxy because brokerage_sync_errors
        # only captures FAILED activities — a sandbox returning 0 activities
        # leaves no rows there either.
        tx_count_result = await session.execute(
            text("SELECT COUNT(*) FROM transactions WHERE portfolio_id = :pid"),
            {"pid": portfolio_id},
        )
        tx_count = int(tx_count_result.scalar() or 0)
        if tx_count == 0:
            logger.warning(
                "repair_skip_no_activity",
                portfolio_id=str(portfolio_id),
                reason="no transactions present — would orphan holdings",
            )
            skipped.append(portfolio_id)
            continue

        eligible.append(portfolio_id)

    return eligible, skipped


async def _run(settings: Settings, *, dry_run: bool, force: bool) -> RepairReport:
    """Execute the repair flow against the configured database."""
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    holdings_zeroed = 0
    dup_groups = 0
    dup_rows = 0

    async with write_factory() as session:
        # 1. Find portfolios with any brokerage connection — and split by the
        #    F-201 guard. With ``--force`` the guard is bypassed.
        eligible_ids, skipped_ids = await _gather_eligible_portfolios(
            session,
            force=force,
        )
        portfolios_with_brokerage = len(eligible_ids) + len(skipped_ids)

        if portfolios_with_brokerage == 0:
            logger.info("no_brokerage_portfolios_found")
            return RepairReport(0, 0, 0, 0)

        # 2. Skipped portfolios — log a summary (each was already logged
        #    individually with its specific skip reason in the gather step).
        if skipped_ids:
            logger.warning(
                "repair_holdings_skipped_by_guard",
                skipped_count=len(skipped_ids),
                eligible_count=len(eligible_ids),
                hint="rerun with --force to override (will orphan holdings if broker is unresponsive)",
            )

        if not eligible_ids:
            # Nothing to do — every portfolio was guarded out. Still run the
            # duplicate-detection step against the original (now empty) set
            # so the operator gets a useful read-only summary.
            return RepairReport(
                portfolios_with_brokerage=portfolios_with_brokerage,
                holdings_zeroed_out=0,
                duplicate_transaction_groups=0,
                duplicate_transaction_rows=0,
                portfolios_skipped_by_guard=len(skipped_ids),
            )

        # 3. Zero-out holdings (or report intent) — only for eligible portfolios.
        count_result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM holdings
                WHERE portfolio_id = ANY(:pids) AND quantity <> 0
                """,
            ),
            {"pids": eligible_ids},
        )
        holdings_zeroed = int(count_result.scalar() or 0)

        if dry_run:
            logger.info(
                "dry_run_would_zero_out_holdings",
                portfolios=len(eligible_ids),
                holdings=holdings_zeroed,
                skipped_by_guard=len(skipped_ids),
                force=force,
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
                {"pids": eligible_ids, "zero": Decimal(0)},
            )

            # F-204: today's snapshot was computed against the (now-stale)
            # pre-zero holdings. Delete it so the next snapshot pass writes
            # a fresh row instead of leaving the user with a contradictory
            # equity curve. Use UTC date because the snapshot worker writes
            # at 21:30 UTC keyed on the UTC calendar date.
            today_utc = datetime.now(tz=UTC).date()
            snap_result = await session.execute(
                text(
                    """
                    DELETE FROM portfolio_value_snapshots
                    WHERE snapshot_date = :today
                      AND portfolio_id = ANY(:pids)
                    """,
                ),
                {"today": today_utc, "pids": eligible_ids},
            )
            await session.commit()
            logger.info(
                "holdings_zeroed",
                portfolios=len(eligible_ids),
                holdings=holdings_zeroed,
                snapshots_deleted=int(snap_result.rowcount or 0),
                snapshot_date=today_utc.isoformat(),
                skipped_by_guard=len(skipped_ids),
                force=force,
            )

        # 4. Duplicate-transactions detection (always read-only). Run against
        #    eligible portfolios — skipped portfolios are already in a
        #    suspect state, the operator should fix the sync first.
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
            {"pids": eligible_ids},
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
        portfolios_skipped_by_guard=len(skipped_ids),
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair holdings drift caused by transaction-replay (BP-264).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without mutating anything.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Bypass the F-201 guard. Required to zero holdings for portfolios "
            "without a recent successful broker sync — operator accepts the risk "
            "of orphaning holdings if the broker doesn't repopulate."
        ),
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

    report = await _run(settings, dry_run=args.dry_run, force=args.force)

    logger.info(
        "repair_complete",
        dry_run=args.dry_run,
        force=args.force,
        portfolios_with_brokerage=report.portfolios_with_brokerage,
        holdings_zeroed_out=report.holdings_zeroed_out,
        duplicate_transaction_groups=report.duplicate_transaction_groups,
        duplicate_transaction_rows=report.duplicate_transaction_rows,
        portfolios_skipped_by_guard=report.portfolios_skipped_by_guard,
    )

    # Exit non-zero only on fatal error — duplicate detection is informational.
    return 0


def main() -> None:
    sys.exit(asyncio.run(amain(sys.argv[1:])))


if __name__ == "__main__":
    main()
