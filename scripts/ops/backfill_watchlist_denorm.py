"""Backfill denormalised columns on ``watchlist_members`` (PLAN-0088 P0-6).

Symptom this fixes
------------------
The watchlist UI showed every row literally labelled "RESOLVING…" instead of
ticker/name/price. Root cause: PLAN-0046 / T-46-2-01 added denormalised
``ticker``, ``name``, ``instrument_id`` columns on ``watchlist_members`` and
``AddWatchlistMemberUseCase`` resolves them at add-time by joining
``instruments.entity_id`` (the KG entity id). For seed/demo data, the
``watchlist_members.entity_id`` is set to the *instrument id* (the
``instruments.id`` column), not the KG entity_id, so the resolver never
matched and the rows kept NULL ticker/name forever — which the frontend
renders as the "resolving…" badge.

What this script does
---------------------
For every ``watchlist_members`` row whose ``ticker`` is NULL, look up the
instrument via TWO strategies and update the denormalised columns:

1. ``wm.entity_id == instruments.id``        — the seed shape.
2. ``wm.entity_id == instruments.entity_id`` — the live add-time shape.

Idempotent: rows that already have a non-NULL ``ticker`` are left alone.

Usage
-----
::

    docker exec worldview-postgres-1 psql -U postgres -d portfolio_db \\
        -f /tmp/backfill_watchlist_denorm.sql

Or via the SQL inlined below — the script intentionally uses raw SQL so it
can be run from anywhere with psql access; no Python deps required.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog
from portfolio.config import Settings
from portfolio.infrastructure.db.session import _build_factories
from sqlalchemy import text

from observability import configure_logging  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)


# Two-strategy backfill: covers both the seed shape (wm.entity_id ==
# instruments.id) and the production add-time shape (wm.entity_id ==
# instruments.entity_id). The COALESCE in the SET keeps the first match.
_BACKFILL_SQL = """
WITH resolved AS (
    SELECT
        wm.id AS member_id,
        COALESCE(i_by_id.symbol, i_by_entity.symbol)    AS symbol,
        COALESCE(i_by_id.name,   i_by_entity.name)      AS name,
        COALESCE(i_by_id.id,     i_by_entity.id)        AS instrument_id
    FROM watchlist_members wm
    LEFT JOIN instruments i_by_id     ON i_by_id.id        = wm.entity_id
    LEFT JOIN instruments i_by_entity ON i_by_entity.entity_id = wm.entity_id
    WHERE wm.ticker IS NULL
)
UPDATE watchlist_members wm
SET
    ticker        = resolved.symbol,
    name          = resolved.name,
    instrument_id = resolved.instrument_id
FROM resolved
WHERE wm.id = resolved.member_id
  AND resolved.symbol IS NOT NULL
RETURNING wm.id, wm.ticker, wm.name;
"""


async def _run(settings: Settings, *, dry_run: bool) -> int:
    # Build a single async session factory — same pattern the snapshot
    # backfill script uses. We do not need a UoW here because this is a
    # single-statement update that is naturally atomic on the DB.
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    async with write_factory() as session:
        if dry_run:
            # Mirror the WHERE clause to count what *would* be updated.
            count_result = await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM watchlist_members wm
                    LEFT JOIN instruments i_by_id     ON i_by_id.id        = wm.entity_id
                    LEFT JOIN instruments i_by_entity ON i_by_entity.entity_id = wm.entity_id
                    WHERE wm.ticker IS NULL
                      AND COALESCE(i_by_id.symbol, i_by_entity.symbol) IS NOT NULL
                    """,
                ),
            )
            n = count_result.scalar_one()
            logger.info("watchlist_denorm_backfill_dry_run", would_update=int(n))
            return 0

        result = await session.execute(text(_BACKFILL_SQL))
        # Pulling the rows surfaces them in the log so an operator can
        # eyeball-confirm the resolved tickers look right.
        rows = result.fetchall()
        await session.commit()
        logger.info("watchlist_denorm_backfill_complete", updated=len(rows))
        for row in rows:
            logger.info("watchlist_member_resolved", id=str(row[0]), ticker=row[1], name=row[2])
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill watchlist_members denormalised columns")
    parser.add_argument("--dry-run", action="store_true", help="Count only; mutate nothing")
    args = parser.parse_args(argv)

    configure_logging("portfolio-backfill-watchlist-denorm")
    settings = Settings()  # type: ignore[call-arg]
    return asyncio.run(_run(settings, dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
