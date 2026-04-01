"""Workers 13G-H: Partition management (PRD §6.7 Block 13G-H).

Worker 13G (monthly): Create current + next month partitions for
  relation_evidence, events, claims.  Also runs at startup.
  IF NOT EXISTS → idempotent.

Worker 13H (yearly): Create yearly partitions for the same tables.
  Also runs at startup.  IF NOT EXISTS → idempotent.

Pruning: drop partitions older than 24 months (13G responsibility).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

_TABLES_RANGE_MONTHLY = ("relation_evidence", "events", "claims")
_RETENTION_MONTHS = 24


class MonthlyPartitionWorker:
    """Creates and prunes monthly range partitions (Worker 13G).

    Args:
        session_factory: Read/write sessionmaker for intelligence_db.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def run(self) -> None:
        """Ensure current and next month partitions exist; prune old ones."""

        now = utc_now()  # type: ignore[no-any-return]
        year: int = now.year  # type: ignore[union-attr]
        month: int = now.month  # type: ignore[union-attr]

        created = 0
        async with self._sf() as session:
            # Create current + next 2 months to stay ahead
            for offset in range(3):
                y, m = _add_months(year, month, offset)
                for table in _TABLES_RANGE_MONTHLY:
                    was_created = await _create_monthly_partition(session, table, y, m)
                    if was_created:
                        created += 1

            # Prune partitions older than 24 months
            pruned = await _prune_old_monthly_partitions(session, year, month)
            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "monthly_partition_worker_complete",
            created=created,
            pruned=pruned,
        )


class YearlyPartitionWorker:
    """Creates yearly partitions at startup and on 1 Jan (Worker 13H).

    Args:
        session_factory: Read/write sessionmaker for intelligence_db.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def run(self) -> None:
        """Ensure current and next year partitions exist."""
        now = utc_now()  # type: ignore[no-any-return]
        year: int = now.year  # type: ignore[union-attr]

        created = 0
        async with self._sf() as session:
            for y in (year, year + 1):
                for table in _TABLES_RANGE_MONTHLY:
                    was_created = await _create_yearly_partition(session, table, y)
                    if was_created:
                        created += 1
            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "yearly_partition_worker_complete",
            created=created,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_monthly_partition(
    session: AsyncSession,
    table: str,
    year: int,
    month: int,
) -> bool:
    """Create a monthly partition if it doesn't exist.  Returns True if created."""
    from sqlalchemy import text

    partition_name = f"{table}_{year}_{month:02d}"
    next_y, next_m = _add_months(year, month, 1)

    # Check existence
    result = await session.execute(
        text(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = :name AND n.nspname = 'public'"
        ),
        {"name": partition_name},
    )
    if result.fetchone():
        return False  # Already exists

    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {partition_name} "
            f"PARTITION OF {table} "
            f"FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_y}-{next_m:02d}-01')"
        )
    )
    logger.info("partition_created", partition=partition_name)  # type: ignore[no-any-return]
    return True


async def _create_yearly_partition(
    session: AsyncSession,
    table: str,
    year: int,
) -> bool:
    """Create a placeholder yearly range partition for a 12-month span."""
    from sqlalchemy import text

    partition_name = f"{table}_{year}"

    result = await session.execute(
        text(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = :name AND n.nspname = 'public'"
        ),
        {"name": partition_name},
    )
    if result.fetchone():
        return False

    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {partition_name} "
            f"PARTITION OF {table} "
            f"FOR VALUES FROM ('{year}-01-01') TO ('{year + 1}-01-01')"
        )
    )
    logger.info("yearly_partition_created", partition=partition_name)  # type: ignore[no-any-return]
    return True


async def _prune_old_monthly_partitions(
    session: AsyncSession,
    current_year: int,
    current_month: int,
) -> int:
    """Drop monthly partitions older than _RETENTION_MONTHS. Returns count dropped."""
    from sqlalchemy import text

    pruned = 0
    # Calculate cutoff month
    cutoff_y, cutoff_m = _add_months(current_year, current_month, -_RETENTION_MONTHS)

    for table in _TABLES_RANGE_MONTHLY:
        # Find existing monthly partitions for this table
        result = await session.execute(
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

        for partition in partitions:
            # Parse year/month from partition name: {table}_{YYYY}_{MM}
            parts = partition.rsplit("_", 2)
            if len(parts) != 3:
                continue
            try:
                p_year = int(parts[1])
                p_month = int(parts[2])
            except ValueError:
                continue

            if (p_year, p_month) < (cutoff_y, cutoff_m):
                await session.execute(text(f"DROP TABLE IF EXISTS {partition} CASCADE"))
                logger.info("partition_pruned", partition=partition)  # type: ignore[no-any-return]
                pruned += 1

    return pruned


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """Add delta months to (year, month), handling wrap-around."""
    total = (year * 12 + (month - 1)) + delta
    y, m = divmod(total, 12)
    return y, m + 1
