"""Backfill ``watchlist_members.{ticker,name,instrument_id}`` for legacy rows.

PLAN-0046 Wave 2 / T-46-2-01 promised this script. F-019 (QA 2026-04-28)
flagged it as missing. This implementation closes the gap.

What it does:
    1. Selects every ``watchlist_member`` row where ``ticker IS NULL``.
    2. For each, looks up the matching local ``instruments`` row by
       ``entity_id`` (the membership entity id is the KG entity id;
       ``instruments.entity_id`` is populated by the
       ``market.instrument.created/updated`` Kafka consumer).
    3. UPDATEs the row's ``ticker``/``name``/``instrument_id`` from the
       instrument cache. Rows with no matching cache entry are LEFT
       UNCHANGED (still NULL) — the user may have to re-add the symbol
       once the instrument syncs.

Idempotency:
    Re-runs are no-ops on rows already populated (filtered out by the
    ``WHERE ticker IS NULL`` clause). Re-runs on rows that still have no
    matching instrument leave them as-is.

Usage:
    # Dry-run — print volumes, mutate nothing.
    python -m portfolio.scripts.backfill_watchlist_member_denorm --dry-run

    # Live — populate denormalised columns where possible.
    python -m portfolio.scripts.backfill_watchlist_member_denorm

Why a single UPDATE-FROM (not a per-row loop):
    The whole job is a 3-column copy from ``instruments`` keyed on
    ``entity_id``. Postgres' UPDATE … FROM is exactly this — one round
    trip, atomic, cheap. A per-row Python loop would do the same thing
    in O(N) round-trips for no benefit.
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
class BackfillReport:
    """Summary of what the backfill did or would do."""

    rows_with_null_ticker: int
    rows_resolvable: int  # match on instruments.entity_id exists
    rows_updated: int
    dry_run: bool


async def _run(settings: Settings, *, dry_run: bool) -> BackfillReport:
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    async with write_factory() as session:
        # 1. How many rows currently have NULL ticker (operational metric)?
        null_count_result = await session.execute(
            text(
                """
                SELECT COUNT(*) FROM watchlist_members WHERE ticker IS NULL
                """,
            ),
        )
        null_count = int(null_count_result.scalar() or 0)

        if null_count == 0:
            logger.info("backfill_watchlist_denorm_nothing_to_do")
            return BackfillReport(0, 0, 0, dry_run)

        # 2. How many of those rows have a matching local instrument?
        # WHY count this separately: the difference between ``null_count``
        # and ``resolvable_count`` is the residual (rows we can't help —
        # the instrument cache simply doesn't have them yet). Surfacing
        # both lets ops know whether to re-run the script after the
        # instrument-event consumer catches up.
        resolvable_result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM watchlist_members wm
                JOIN instruments i ON i.entity_id = wm.entity_id
                WHERE wm.ticker IS NULL
                """,
            ),
        )
        resolvable = int(resolvable_result.scalar() or 0)

        if dry_run:
            logger.info(
                "backfill_watchlist_denorm_dry_run",
                rows_with_null_ticker=null_count,
                rows_resolvable=resolvable,
                rows_unresolvable=null_count - resolvable,
            )
            return BackfillReport(null_count, resolvable, 0, dry_run)

        # 3. Live — single UPDATE-FROM.
        # WHY ``WHERE wm.ticker IS NULL``: this script must never overwrite
        # already-populated denormalised fields. Once a row has been
        # resolved at add-time we trust that snapshot rather than re-deriving
        # it from a possibly-stale instruments row.
        update_result = await session.execute(
            text(
                """
                UPDATE watchlist_members AS wm
                SET ticker = i.symbol,
                    name = i.name,
                    instrument_id = i.id
                FROM instruments AS i
                WHERE i.entity_id = wm.entity_id
                  AND wm.ticker IS NULL
                """,
            ),
        )
        await session.commit()
        updated = int(update_result.rowcount or 0)

        logger.info(
            "backfill_watchlist_denorm_complete",
            rows_with_null_ticker=null_count,
            rows_resolvable=resolvable,
            rows_updated=updated,
        )
        return BackfillReport(null_count, resolvable, updated, dry_run)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill watchlist_member denormalised fields (PLAN-0046 / F-019).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report volumes only; mutate nothing.",
    )
    return parser.parse_args(argv)


async def amain(argv: list[str]) -> int:
    args = _parse_args(argv)
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="portfolio-backfill-watchlist-denorm",
        level=settings.log_level,
        json=settings.log_json,
    )

    report = await _run(settings, dry_run=args.dry_run)

    logger.info(
        "backfill_watchlist_denorm_report",
        rows_with_null_ticker=report.rows_with_null_ticker,
        rows_resolvable=report.rows_resolvable,
        rows_updated=report.rows_updated,
        dry_run=report.dry_run,
    )
    return 0


def main() -> None:
    sys.exit(asyncio.run(amain(sys.argv[1:])))


if __name__ == "__main__":
    main()
