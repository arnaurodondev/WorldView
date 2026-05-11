"""Partition retention script — detach and drop partitions older than 24 months.

D-004 decision: 24-month rolling retention for RANGE-partitioned tables in
intelligence_db: ``relation_evidence``, ``claims``, ``events``.

Usage:
    # Dry run (default) — list partitions that would be dropped
    python scripts/partition_retention.py

    # Actually detach and drop
    python scripts/partition_retention.py --execute

    # Custom retention period (in months)
    python scripts/partition_retention.py --retention-months 12 --execute

    # Custom database URL
    python scripts/partition_retention.py --database-url postgresql+asyncpg://user:pass@host/intelligence_db --execute

Environment:
    INTELLIGENCE_DB_URL — PostgreSQL connection string for intelligence_db.
                          Falls back to ``postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db``.

Schedule:
    Run monthly via cron or Kubernetes CronJob.  See docs/runbooks/partition-retention.md.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

# ---------------------------------------------------------------------------
# structlog setup — falls back to stdlib if structlog is unavailable
# (the script may run outside the repo venv for ops convenience)
# ---------------------------------------------------------------------------
try:
    from observability import get_logger  # type: ignore[import-untyped]

    logger = get_logger("partition_retention")  # type: ignore[no-any-return]
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("partition_retention")  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_RETENTION_MONTHS = 24
_PARTITIONED_TABLES = ("relation_evidence", "claims", "events")
_DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"
_PARTITION_PATTERN = re.compile(r"^(.+)_(\d{4})_(\d{2})$")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """Add *delta* months to (year, month), handling wrap-around."""
    total = (year * 12 + (month - 1)) + delta
    y, m = divmod(total, 12)
    return y, m + 1


async def run_retention(
    database_url: str,
    retention_months: int,
    *,
    execute: bool = False,
) -> dict[str, list[str]]:
    """Identify and optionally drop partitions older than *retention_months*.

    Returns a dict with keys ``"detached"`` and ``"skipped"`` listing partition names.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url, echo=False)

    # Current month for cutoff calculation
    from datetime import UTC, datetime

    now = datetime.now(tz=UTC)
    cutoff_y, cutoff_m = _add_months(now.year, now.month, -retention_months)

    detached: list[str] = []
    skipped: list[str] = []

    async with engine.begin() as conn:
        for table in _PARTITIONED_TABLES:
            # Find monthly partitions matching {table}_{YYYY}_{MM}
            result = await conn.execute(
                text("""
SELECT c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname ~ :pattern
ORDER BY c.relname
"""),
                {"pattern": f"^{table}_[0-9]{{4}}_[0-9]{{2}}$"},
            )
            partitions = [row[0] for row in result.fetchall()]

            for partition_name in partitions:
                match = _PARTITION_PATTERN.match(partition_name)
                if not match:
                    skipped.append(partition_name)
                    continue

                p_year = int(match.group(2))
                p_month = int(match.group(3))

                if (p_year, p_month) >= (cutoff_y, cutoff_m):
                    # Partition is within retention window — keep it
                    continue

                if execute:
                    # Step 1: Detach the partition from the parent table
                    logger.info(  # type: ignore[union-attr]
                        "detaching_partition",
                        partition=partition_name,
                        parent_table=table,
                    )
                    await conn.execute(text(f"ALTER TABLE {table} DETACH PARTITION {partition_name}"))

                    # Step 2: Drop the detached partition
                    logger.info(  # type: ignore[union-attr]
                        "dropping_partition",
                        partition=partition_name,
                    )
                    await conn.execute(text(f"DROP TABLE IF EXISTS {partition_name} CASCADE"))
                    detached.append(partition_name)
                else:
                    logger.info(  # type: ignore[union-attr]
                        "would_drop_partition",
                        partition=partition_name,
                        parent_table=table,
                        partition_date=f"{p_year}-{p_month:02d}",
                        cutoff_date=f"{cutoff_y}-{cutoff_m:02d}",
                    )
                    detached.append(partition_name)

    await engine.dispose()
    return {"detached": detached, "skipped": skipped}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Drop intelligence_db partitions older than the retention window.")
    parser.add_argument(
        "--retention-months",
        type=int,
        default=_DEFAULT_RETENTION_MONTHS,
        help=f"Number of months to retain (default: {_DEFAULT_RETENTION_MONTHS})",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=os.environ.get("INTELLIGENCE_DB_URL", _DEFAULT_DB_URL),
        help="PostgreSQL connection string (default: $INTELLIGENCE_DB_URL)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually detach and drop partitions (default: dry run)",
    )
    args = parser.parse_args()

    logger.info(  # type: ignore[union-attr]
        "partition_retention_start",
        retention_months=args.retention_months,
        execute=args.execute,
        database_url=args.database_url.split("@")[-1],  # Redact credentials
    )

    result = asyncio.run(
        run_retention(
            database_url=args.database_url,
            retention_months=args.retention_months,
            execute=args.execute,
        )
    )

    if result["detached"]:
        action = "dropped" if args.execute else "would drop"
        logger.info(  # type: ignore[union-attr]
            "partition_retention_complete",
            action=action,
            count=len(result["detached"]),
            partitions=result["detached"],
        )
    else:
        logger.info("partition_retention_complete", action="no_partitions_to_drop")  # type: ignore[union-attr]

    if not args.execute and result["detached"]:
        print(f"\nDry run: {len(result['detached'])} partition(s) would be dropped.")
        print("Re-run with --execute to apply changes.")
        sys.exit(0)


if __name__ == "__main__":
    main()
