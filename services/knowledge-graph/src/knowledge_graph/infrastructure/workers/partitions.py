"""Workers 13G-H: Partition management (PRD §6.7 Block 13G-H).

Worker 13G (monthly): Create current + next month partitions for
  relation_evidence, events, claims.  Also runs at startup.
  IF NOT EXISTS → idempotent.

Worker 13H (yearly): Create yearly partitions for the same tables.
  Also runs at startup.  IF NOT EXISTS → idempotent.

Pruning: drop partitions older than 24 months (13G responsibility).

DEFAULT-partition hardening (residual review 2026-07-16, see migration 0068):
  ``relation_evidence`` now carries a DEFAULT catch-all partition. Postgres
  refuses to CREATE/ATTACH a new range partition whenever the DEFAULT partition
  already holds a row that would belong in the new range ("partition constraint
  ... would be violated by some row"). Because this worker creates partitions at
  RUNTIME, a single such conflict — a future-dated row landing in DEFAULT before
  its monthly partition is created — would roll back the whole cycle every run
  and wedge partition maintenance (the same poison-batch shape as the original
  promoter bug). To make one failure non-fatal:
    * each partition is created in its OWN transaction (own session), so a
      failure on one partition can never roll back the creation of the others;
    * a DEFAULT-conflict is caught and treated as a non-fatal WARN (skip-and-
      continue) rather than propagating and wedging the cycle;
    * pruning is DEFAULT-aware: rows in the DEFAULT partition older than the
      retention cutoff are deleted (they otherwise escape the 24-month policy).
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

# Substrings that identify a "row already in DEFAULT partition" conflict raised
# when CREATE ... PARTITION OF collides with rows Postgres already routed into
# the DEFAULT partition. Matched case-insensitively against the exception text.
# Postgres wording: "updated partition constraint for default partition
# \"relation_evidence_default\" would be violated by some row".
_DEFAULT_CONFLICT_MARKERS = (
    "default partition",
    "would be violated by some row",
    "would overlap",
)


def _is_default_conflict(exc: BaseException) -> bool:
    """Return True if ``exc`` is a DEFAULT-partition create/attach conflict.

    Such a conflict is expected and non-fatal: it only means a row for the new
    range already sits in the DEFAULT partition. Wedging the whole maintenance
    cycle on it would reproduce the poison-batch bug migration 0068 fixed.
    """
    text_blob = str(exc).lower()
    # Walk the cause/context chain too — SQLAlchemy wraps the asyncpg error.
    cursor: BaseException | None = exc
    while cursor is not None:
        text_blob += " " + str(cursor).lower()
        cursor = cursor.__cause__ or cursor.__context__
    return any(marker in text_blob for marker in _DEFAULT_CONFLICT_MARKERS)


class MonthlyPartitionWorker:
    """Creates and prunes monthly range partitions (Worker 13G).

    Args:
    ----
        session_factory: Read/write sessionmaker for intelligence_db.

    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def run(self) -> None:
        """Ensure current and next month partitions exist; prune old ones.

        Each partition is created in its OWN transaction so a failure on one
        (e.g. a DEFAULT-partition conflict) can never roll back the others or
        wedge the whole cycle. Pruning runs in its own transaction too.
        """
        now = utc_now()  # type: ignore[no-any-return]
        year: int = now.year  # type: ignore[union-attr]
        month: int = now.month  # type: ignore[union-attr]

        created = 0
        skipped = 0
        # Create current + next 2 months to stay ahead. One transaction per
        # partition: isolation means a single failure is contained.
        for offset in range(3):
            y, m = _add_months(year, month, offset)
            for table in _TABLES_RANGE_MONTHLY:
                outcome = await self._create_one(table, y, m)
                if outcome == "created":
                    created += 1
                elif outcome == "skipped":
                    skipped += 1

        # Prune partitions older than 24 months (own transaction).
        pruned = 0
        try:
            async with self._sf() as session:
                pruned = await _prune_old_monthly_partitions(session, year, month)
                await session.commit()
        except Exception:
            logger.warning("monthly_partition_prune_failed", exc_info=True)  # type: ignore[no-any-return]

        logger.info(  # type: ignore[no-any-return]
            "monthly_partition_worker_complete",
            created=created,
            skipped=skipped,
            pruned=pruned,
        )

    async def _create_one(self, table: str, year: int, month: int) -> str:
        """Create one monthly partition in its own transaction.

        Returns ``"created"``, ``"exists"``, or ``"skipped"`` (non-fatal
        DEFAULT-partition conflict). Never raises for a DEFAULT conflict.
        """
        try:
            async with self._sf() as session:
                was_created = await _create_monthly_partition(session, table, year, month)
                await session.commit()
                return "created" if was_created else "exists"
        except Exception as exc:
            if _is_default_conflict(exc):
                logger.warning(  # type: ignore[no-any-return]
                    "monthly_partition_default_conflict",
                    table=table,
                    partition=f"{table}_{year}_{month:02d}",
                    detail=(
                        "DEFAULT partition already holds a row for this range; "
                        "skipping create so the cycle is not wedged. Rehome rows "
                        "out of DEFAULT via a migration to reclaim this partition."
                    ),
                )
                return "skipped"
            # Any other error is isolated to this partition — log and continue
            # so one bad partition cannot wedge maintenance of the others.
            logger.warning(  # type: ignore[no-any-return]
                "monthly_partition_create_failed",
                table=table,
                partition=f"{table}_{year}_{month:02d}",
                exc_info=True,
            )
            return "skipped"


class YearlyPartitionWorker:
    """Creates yearly partitions at startup and on 1 Jan (Worker 13H).

    Args:
    ----
        session_factory: Read/write sessionmaker for intelligence_db.

    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def run(self) -> None:
        """Ensure current and next year partitions exist.

        Each partition is created in its OWN transaction so a DEFAULT-partition
        conflict (or any single failure) cannot wedge the whole cycle.
        """
        now = utc_now()  # type: ignore[no-any-return]
        year: int = now.year  # type: ignore[union-attr]

        created = 0
        skipped = 0
        for y in (year, year + 1):
            for table in _TABLES_RANGE_MONTHLY:
                outcome = await self._create_one(table, y)
                if outcome == "created":
                    created += 1
                elif outcome == "skipped":
                    skipped += 1

        logger.info(  # type: ignore[no-any-return]
            "yearly_partition_worker_complete",
            created=created,
            skipped=skipped,
        )

    async def _create_one(self, table: str, year: int) -> str:
        """Create one yearly partition in its own transaction; DEFAULT-safe."""
        try:
            async with self._sf() as session:
                was_created = await _create_yearly_partition(session, table, year)
                await session.commit()
                return "created" if was_created else "exists"
        except Exception as exc:
            if _is_default_conflict(exc):
                logger.warning(  # type: ignore[no-any-return]
                    "yearly_partition_default_conflict",
                    table=table,
                    partition=f"{table}_{year}",
                    detail="DEFAULT partition holds a row for this range; skipping create.",
                )
                return "skipped"
            logger.warning(  # type: ignore[no-any-return]
                "yearly_partition_create_failed",
                table=table,
                partition=f"{table}_{year}",
                exc_info=True,
            )
            return "skipped"


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
            "WHERE c.relname = :name AND n.nspname = 'public'",
        ),
        {"name": partition_name},
    )
    if result.fetchone():
        return False  # Already exists

    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {partition_name} "
            f"PARTITION OF {table} "
            f"FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_y}-{next_m:02d}-01')",
        ),
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
            "WHERE c.relname = :name AND n.nspname = 'public'",
        ),
        {"name": partition_name},
    )
    if result.fetchone():
        return False

    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {partition_name} "
            f"PARTITION OF {table} "
            f"FOR VALUES FROM ('{year}-01-01') TO ('{year + 1}-01-01')",
        ),
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

        # DEFAULT-aware retention: rows Postgres routed into the DEFAULT
        # partition (out-of-window dates) are NOT covered by the DROP-partition
        # logic above and would otherwise escape the 24-month policy forever.
        # Delete DEFAULT rows older than the same cutoff so retention is uniform.
        pruned += await _prune_default_partition_rows(session, table, cutoff_y, cutoff_m)

    return pruned


async def _prune_default_partition_rows(
    session: AsyncSession,
    table: str,
    cutoff_year: int,
    cutoff_month: int,
) -> int:
    """Delete rows in ``{table}`` DEFAULT partition older than the cutoff.

    Whole monthly partitions are dropped by name; the DEFAULT partition cannot
    be dropped (it is the catch-all), so its old rows must be deleted directly
    to honour the 24-month retention policy. No-op when the table has no DEFAULT
    partition. Returns the number of rows deleted (0 or the delete rowcount).
    """
    from sqlalchemy import text

    default_name = f"{table}_default"

    # Only act if a DEFAULT partition actually exists for this table.
    exists = await session.execute(
        text(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = :name AND n.nspname = 'public'",
        ),
        {"name": default_name},
    )
    if not exists.fetchone():
        return 0

    # Resolve the parent table's range partition key column from the catalog so
    # the DELETE targets the correct column (evidence_date vs created_at, …).
    key_col_row = (
        await session.execute(
            text("""
SELECT a.attname
FROM pg_partitioned_table pt
JOIN pg_class c ON c.oid = pt.partrelid
JOIN unnest(pt.partattrs) WITH ORDINALITY AS k(attnum, ord) ON true
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
WHERE c.relname = :table
ORDER BY k.ord
LIMIT 1
"""),
            {"table": table},
        )
    ).fetchone()
    if key_col_row is None:
        return 0
    key_col = str(key_col_row[0])
    # Validate the identifier against the catalog result to keep it injection
    # -safe before interpolating it into DDL/DML text.
    if not key_col.isidentifier():
        logger.warning(  # type: ignore[no-any-return]
            "default_partition_prune_bad_key",
            table=table,
            key_col=key_col,
        )
        return 0

    cutoff_date = f"{cutoff_year}-{cutoff_month:02d}-01"

    # from the hardcoded `_TABLES_RANGE_MONTHLY` tuple and `key_col` comes from the
    # pg catalog validated via `.isidentifier()` above; the date value is bound.
    result = await session.execute(
        text(f"DELETE FROM {default_name} WHERE {key_col} < :cutoff"),  # noqa: S608
        {"cutoff": cutoff_date},
    )
    # `rowcount` lives on the underlying CursorResult; guard for typing since the
    # generic Result protocol does not expose it.
    deleted = int(getattr(result, "rowcount", 0) or 0)
    if deleted:
        logger.info(  # type: ignore[no-any-return]
            "default_partition_rows_pruned",
            partition=default_name,
            deleted=deleted,
            cutoff=cutoff_date,
        )
    return deleted


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """Add delta months to (year, month), handling wrap-around."""
    total = (year * 12 + (month - 1)) + delta
    y, m = divmod(total, 12)
    return y, m + 1
