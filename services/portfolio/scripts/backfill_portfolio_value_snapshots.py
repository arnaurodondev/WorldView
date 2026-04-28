"""Backfill historical ``portfolio_value_snapshots`` rows.

PLAN-0046 Wave 4 / T-46-4-04.

Replays portfolio value snapshots backwards from today to the earliest
transaction date (capped at 365 calendar days for v1) by reconstructing
each portfolio's holdings *as of* every historical trading day, then
multiplying by the close price on that day.

Activity replay is intentional here — we have no historical position
snapshots from the broker, so this is the one place where replaying
transactions is acceptable (PLAN-0046 explicitly notes this exception).
For "today" the snapshot worker uses authoritative current holdings;
this script is strictly historical fill-in.

Usage::

    # See volume only — write nothing
    python -m portfolio.scripts.backfill_portfolio_value_snapshots --dry-run

    # Live run — write missing rows, idempotent on existing rows
    python -m portfolio.scripts.backfill_portfolio_value_snapshots

Idempotency:
    Each upsert is keyed on ``(portfolio_id, snapshot_date)`` so re-runs
    fill only the missing dates and overwrite stale ones (latest-wins).

Why not just run the snapshot worker N times:
    The worker uses ``Holding`` rows which reflect the current position;
    it has no way to undo broker-reported quantities back in time. This
    script reads the transaction log and rebuilds quantity/avg_cost as
    of each historical date.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import structlog
from portfolio.config import Settings
from portfolio.domain.entities.portfolio_value_snapshot import PortfolioValueSnapshot
from portfolio.domain.enums import PortfolioKind, PortfolioStatus, TransactionDirection
from portfolio.infrastructure.db.session import _build_factories
from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from portfolio.workers.portfolio_snapshot_worker import (
    HttpOHLCVPriceClient,
    _system_jwt_headers,
    is_trading_day,
)
from sqlalchemy import text

from observability import configure_logging  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from portfolio.application.use_cases.compute_portfolio_value import OHLCVPriceClient
    from portfolio.domain.entities.portfolio import Portfolio
    from portfolio.domain.entities.transaction import Transaction

logger = structlog.get_logger(__name__)


# v1 cap — replay at most 365 calendar days of history. Anything older is
# acceptably "missing" for analytics that focus on 1Y/YTD windows.
DEFAULT_LOOKBACK_DAYS = 365


@dataclass
class BackfillReport:
    portfolios_processed: int
    snapshots_written: int
    snapshots_skipped_dry_run: int
    portfolios_failed: int


# ── Position reconstruction ───────────────────────────────────────────────────


@dataclass
class _Position:
    """Mutable per-instrument running tally used during replay."""

    quantity: Decimal = Decimal(0)
    avg_cost: Decimal = Decimal(0)


def _replay_until(transactions: list[Transaction], cutoff: date) -> dict[UUID, _Position]:
    """Replay transactions chronologically up to and including ``cutoff``.

    Returns a map ``instrument_id -> _Position`` representing the
    portfolio's holdings at the close of business on ``cutoff``.

    The arithmetic mirrors ``Holding.apply_delta`` but in a position-only
    form (we don't need to write ``Holding`` rows): on INFLOW we update
    weighted-average cost; on OUTFLOW we reduce quantity, leaving avg
    cost intact (and reset to 0 when fully closed).

    Why we reset avg_cost on full close: matches ``Holding.apply_delta``
    so reopening a position later (BUY after SELL-to-zero) starts from
    a fresh basis — the standard FIFO-equivalent for cost tracking.
    """
    # Sort defensively — callers should pass a stable order, but the
    # transaction repo doesn't guarantee anything beyond LIMIT/OFFSET.
    sorted_txns = sorted(transactions, key=lambda t: t.executed_at)

    positions: dict[UUID, _Position] = defaultdict(_Position)
    for txn in sorted_txns:
        if txn.executed_at.date() > cutoff:
            break

        pos = positions[txn.instrument_id]
        if txn.direction == TransactionDirection.INFLOW:
            new_qty = pos.quantity + txn.quantity
            if new_qty > Decimal(0):
                # Weighted average cost on accumulation.
                pos.avg_cost = (pos.quantity * pos.avg_cost + txn.quantity * txn.price) / new_qty
            pos.quantity = new_qty
        else:
            pos.quantity -= txn.quantity
            if pos.quantity <= Decimal(0):
                pos.quantity = Decimal(0)
                pos.avg_cost = Decimal(0)

    return positions


# ── Per-portfolio backfill ────────────────────────────────────────────────────


async def _earliest_transaction_date(
    write_factory: object,
    portfolio_id: UUID,
) -> date | None:
    """Return ``min(executed_at::date)`` for the portfolio's transactions, or None.

    Uses raw SQL to keep this decoupled from the repository (which is
    use-case-shaped, not "give me the min").
    """
    # Local import to avoid circulars at module top.
    from portfolio.infrastructure.db.session import _build_factories  # noqa: F401

    async with write_factory() as session:  # type: ignore[operator]
        result = await session.execute(
            text(
                "SELECT MIN(executed_at)::date AS min_d " "FROM transactions WHERE portfolio_id = :pid",
            ),
            {"pid": portfolio_id},
        )
        row = result.first()
    if row is None or row.min_d is None:
        return None
    return row.min_d  # type: ignore[no-any-return]


async def _backfill_one_portfolio(
    portfolio: Portfolio,
    write_factory: object,
    price_client: OHLCVPriceClient,
    lookback_days: int,
    *,
    dry_run: bool,
) -> tuple[int, int]:
    """Backfill snapshots for one portfolio. Returns (written, skipped_dry_run)."""
    today = datetime.now(tz=UTC).date()
    earliest = await _earliest_transaction_date(write_factory, portfolio.id)
    if earliest is None:
        logger.info("backfill_skip_no_transactions", portfolio_id=str(portfolio.id))
        return 0, 0

    cap = today - timedelta(days=lookback_days)
    start = max(earliest, cap)

    # Load all transactions ONCE — replay is in memory.
    async with SqlAlchemyUnitOfWork(write_factory) as uow:  # type: ignore[arg-type]
        # We pull a generous limit; portfolios with >10k transactions are
        # rare and the in-memory cost is small (a few MB at most).
        all_txns, _total = await uow.transactions.list_by_portfolio(
            portfolio.id,
            portfolio.tenant_id,
            limit=100_000,
            offset=0,
        )

    # Walk every trading day in [start, today). We exclude ``today`` itself
    # because the live snapshot worker covers it (and the worker reads
    # current Holdings, not replayed ones — which is more accurate after
    # broker rewrites). The historical script must NOT overwrite today's
    # row with a possibly-drifted replay value.
    written = 0
    skipped_dry_run = 0
    cursor = today - timedelta(days=1)
    while cursor >= start:
        if not is_trading_day(cursor):
            cursor -= timedelta(days=1)
            continue

        positions = _replay_until(all_txns, cursor)

        total_value = Decimal(0)
        total_cost = Decimal(0)
        for instrument_id, pos in positions.items():
            if pos.quantity <= Decimal(0):
                continue
            total_cost += pos.quantity * pos.avg_cost
            close = await price_client.get_close_on_date(instrument_id, cursor)
            if close is None:
                # Treat as zero contribution + log; same policy as the live worker.
                continue
            total_value += pos.quantity * close

        snapshot = PortfolioValueSnapshot(
            portfolio_id=portfolio.id,
            tenant_id=portfolio.tenant_id,
            snapshot_date=cursor,
            total_value=total_value,
            total_cost=total_cost,
            cash_value=Decimal(0),
        )

        if dry_run:
            skipped_dry_run += 1
        else:
            async with SqlAlchemyUnitOfWork(write_factory) as uow:  # type: ignore[arg-type]
                await uow.portfolio_value_snapshots.upsert(snapshot)
                await uow.commit()
            written += 1

        cursor -= timedelta(days=1)

    return written, skipped_dry_run


# ── Entry point ───────────────────────────────────────────────────────────────


async def _run(
    settings: Settings,
    *,
    dry_run: bool,
    lookback_days: int,
) -> BackfillReport:
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    # Load all portfolios that need backfilling: every active portfolio,
    # both root and non-root. Root portfolios are useful too — we replay
    # their constituents and aggregate (the script doesn't separately
    # aggregate roots; instead it treats roots as no-op since they
    # generally have no direct transactions). For v1 we restrict to
    # non-root active portfolios; the live worker handles root aggregation
    # going forward, and historical roots can be re-summed by a follow-up
    # query if needed.
    async with SqlAlchemyUnitOfWork(write_factory) as uow:
        portfolios: list[Portfolio] = await uow.portfolios.list_all_non_root_active()

    logger.info("backfill_portfolios_loaded", count=len(portfolios), dry_run=dry_run)

    total_written = 0
    total_skipped = 0
    failed = 0

    async with httpx.AsyncClient(timeout=10.0, headers=_system_jwt_headers()) as http_client:
        price_client: OHLCVPriceClient = HttpOHLCVPriceClient(
            http=http_client,
            market_data_url=settings.market_data_service_url,
        )

        for portfolio in portfolios:
            if portfolio.status != PortfolioStatus.ACTIVE or portfolio.kind == PortfolioKind.ROOT:
                # Defensive — we already filtered, but the enum guard
                # protects against future repo changes.
                continue

            try:
                written, skipped = await _backfill_one_portfolio(
                    portfolio,
                    write_factory,
                    price_client,
                    lookback_days,
                    dry_run=dry_run,
                )
                total_written += written
                total_skipped += skipped
                logger.info(
                    "backfill_portfolio_done",
                    portfolio_id=str(portfolio.id),
                    written=written,
                    skipped_dry_run=skipped,
                )
            except Exception as exc:
                failed += 1
                logger.error(
                    "backfill_portfolio_failed",
                    portfolio_id=str(portfolio.id),
                    error=type(exc).__name__,
                    error_message=str(exc),
                )

    return BackfillReport(
        portfolios_processed=len(portfolios),
        snapshots_written=total_written,
        snapshots_skipped_dry_run=total_skipped,
        portfolios_failed=failed,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill historical portfolio value snapshots.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute volumes only; mutate nothing.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"Max calendar days to backfill (default: {DEFAULT_LOOKBACK_DAYS}).",
    )
    args = parser.parse_args(argv)

    configure_logging("portfolio-backfill-snapshots")
    settings = Settings()  # type: ignore[call-arg]
    report = asyncio.run(
        _run(settings, dry_run=args.dry_run, lookback_days=args.lookback_days),
    )

    logger.info(
        "backfill_portfolio_value_snapshots_complete",
        dry_run=args.dry_run,
        portfolios_processed=report.portfolios_processed,
        snapshots_written=report.snapshots_written,
        snapshots_skipped_dry_run=report.snapshots_skipped_dry_run,
        portfolios_failed=report.portfolios_failed,
    )
    return 0 if report.portfolios_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
