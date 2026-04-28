"""Backfill ``watchlist_members.{ticker,name,instrument_id}`` for legacy rows.

PLAN-0046 Wave 2 / T-46-2-01 promised this script. F-019 (QA 2026-04-28)
flagged it as missing. This implementation closes the gap.

What it does:
    1. Selects every ``watchlist_member`` row where ``ticker IS NULL``.
    2. For each, looks up the matching local ``instruments`` row using a
       **dual-key resolution path** (F-304, QA iter-3): try
       ``instruments.entity_id`` first (the canonical KG entity id, set
       by the ``market.instrument.created/updated`` Kafka consumer),
       then fall back to ``instruments.id`` (the row PK, used by some
       legacy seed paths that conflate the two). This makes the script
       robust against both production data (entity_id from KG) AND seed
       data (entity_id literally equal to instruments.id).
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
    ``entity_id`` (or ``id`` as fallback). Postgres' UPDATE … FROM is
    exactly this — one round trip, atomic, cheap. A per-row Python loop
    would do the same thing in O(N) round-trips for no benefit.
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
        #
        # F-304 (QA iter-3): the count uses the dual-key OR predicate so
        # both seed-style (entity_id == instruments.id) and KG-style
        # (entity_id == instruments.entity_id) rows are counted as
        # resolvable.
        resolvable_result = await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT wm.id)
                FROM watchlist_members wm
                JOIN instruments i
                  ON i.entity_id = wm.entity_id
                  OR i.id = wm.entity_id
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

        # 3. Live — TWO UPDATE-FROMs in sequence so the ``entity_id``-keyed
        # path always wins over the ``id``-keyed fallback (matters when an
        # instrument has both columns populated with different values —
        # the canonical KG entity_id is the right one). The ``WHERE
        # wm.ticker IS NULL`` clause makes the second update naturally
        # idempotent: rows the first one resolved are filtered out.
        #
        # WHY ``WHERE wm.ticker IS NULL``: this script must never overwrite
        # already-populated denormalised fields. Once a row has been
        # resolved at add-time we trust that snapshot rather than re-deriving
        # it from a possibly-stale instruments row.
        update_primary = await session.execute(
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
        # F-304: fallback for seed-style rows where wm.entity_id holds the
        # instruments.id PK rather than the KG entity_id. This pass picks
        # up only rows the primary pass left behind (still NULL ticker).
        update_fallback = await session.execute(
            text(
                """
                UPDATE watchlist_members AS wm
                SET ticker = i.symbol,
                    name = i.name,
                    instrument_id = i.id
                FROM instruments AS i
                WHERE i.id = wm.entity_id
                  AND wm.ticker IS NULL
                """,
            ),
        )
        await session.commit()
        updated_primary = int(update_primary.rowcount or 0)
        updated_fallback = int(update_fallback.rowcount or 0)
        updated = updated_primary + updated_fallback

        logger.info(
            "backfill_watchlist_denorm_complete",
            rows_with_null_ticker=null_count,
            rows_resolvable=resolvable,
            rows_updated=updated,
            rows_updated_via_entity_id=updated_primary,
            rows_updated_via_instrument_id=updated_fallback,
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
