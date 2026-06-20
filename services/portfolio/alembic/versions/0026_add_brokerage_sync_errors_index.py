"""Add index on brokerage_sync_errors.brokerage_connection_id (W3 - FR-7).

Revision ID: 0026
Revises: 0023
Create Date: 2026-06-20

WHY THIS INDEX:
GetHoldingsUseCase.execute() now calls count_for_connection() on the
BrokerageTransactionSyncErrorRepository for every GET /holdings/{portfolio_id}
request for a BROKERAGE portfolio. Without an index on brokerage_connection_id
this is a full table scan -- O(total_error_rows) per holdings request.

The table is append-only (errors are immutable) so the index is never
invalidated by UPDATEs. Expected cardinality: <1000 rows per tenant in
normal operation; extreme cases (runaway sync error) may see 10k+.

Technique:
  CREATE INDEX CONCURRENTLY avoids a full table lock. We must use AUTOCOMMIT
  isolation level because PostgreSQL requires a non-transactional context for
  concurrent index builds. This follows the same pattern as migration 0022.

Rollback:
  DROP INDEX CONCURRENTLY IF EXISTS is safe -- queries that were relying on
  the index fall back to seq-scan. The ORM query in count_for_connection()
  continues to work correctly, just slower.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
# WHY down_revision="0025" (not "0023"): 0024 and 0025 already depend on 0023
# (chain: 0023→0024→0025). Setting down_revision to 0023 would create a two-head
# branch that Alembic refuses to apply ("Multiple head revisions"). 0026 is a
# linear successor of 0025 — the CONCURRENTLY index has no DDL dependency on
# 0024/0025, so this ordering is safe.
revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add ix_brokerage_sync_errors_connection_id index using CONCURRENTLY.

    Must run outside a transaction (AUTOCOMMIT) to avoid locking the table.
    """
    conn = op.get_bind()
    conn.execution_options(isolation_level="AUTOCOMMIT").execute(
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_brokerage_sync_errors_connection_id
            ON brokerage_sync_errors (brokerage_connection_id)
        """,  # -- not user input, safe literal
    )


def downgrade() -> None:
    """Drop the index using CONCURRENTLY to avoid a table lock."""
    conn = op.get_bind()
    conn.execution_options(isolation_level="AUTOCOMMIT").execute(
        "DROP INDEX CONCURRENTLY IF EXISTS ix_brokerage_sync_errors_connection_id",
    )
