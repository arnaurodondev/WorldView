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

import sqlalchemy.exc
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
    """Add ix_brokerage_sync_errors_connection_id index.

    In production we use CREATE INDEX CONCURRENTLY (no table lock).  That
    requires AUTOCOMMIT — i.e. no active SQLAlchemy transaction.  Alembic's
    do_run_migrations wrapper calls context.begin_transaction() first, so in
    test/CI environments (testcontainers) the connection already holds a
    Transaction() object and SQLAlchemy raises InvalidRequestError when we
    try to switch isolation_level.

    Strategy: attempt the CONCURRENTLY variant first.  If the isolation_level
    change is rejected (test transaction wrapper), fall back to the standard
    non-blocking CREATE INDEX IF NOT EXISTS which runs fine inside a
    transaction — the table is small in CI and the brief metadata lock is
    acceptable there.
    """
    conn = op.get_bind()
    try:
        # Production path: switch to AUTOCOMMIT, then issue CONCURRENTLY DDL.
        # execution_options() returns a new connection proxy; the original
        # connection is not modified so Alembic's commit/rollback still works.
        conn.execution_options(isolation_level="AUTOCOMMIT").execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_brokerage_sync_errors_connection_id
                ON brokerage_sync_errors (brokerage_connection_id)
            """,  # -- not user input, safe literal
        )
    except sqlalchemy.exc.InvalidRequestError:
        # DP-007: only catch the specific error raised when AUTOCOMMIT isolation
        # level change is rejected because an existing transaction is already open
        # (test/CI path with testcontainers).  A bare `except Exception` was too
        # broad — it would silently swallow real errors (network failures, OOM,
        # permission denied) and attempt the fallback, losing the original error
        # context.  InvalidRequestError is the precise SQLAlchemy error for
        # "cannot change isolation level within a transaction".
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_brokerage_sync_errors_connection_id
                ON brokerage_sync_errors (brokerage_connection_id)
            """,  # -- not user input, safe literal
        )


def downgrade() -> None:
    """Drop the index (prefer CONCURRENTLY; fall back for test environments)."""
    conn = op.get_bind()
    try:
        conn.execution_options(isolation_level="AUTOCOMMIT").execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_brokerage_sync_errors_connection_id",
        )
    except sqlalchemy.exc.InvalidRequestError:
        # Same narrow catch as upgrade() — only swallow the transaction-context
        # isolation error, not real failures.
        conn.execute(
            "DROP INDEX IF EXISTS ix_brokerage_sync_errors_connection_id",
        )
