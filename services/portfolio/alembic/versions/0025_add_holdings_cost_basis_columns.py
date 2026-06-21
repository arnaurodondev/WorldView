"""Add cost_basis_per_unit and total_cost_basis columns to holdings.

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-20

PLAN-0114 W1 / T-W1-02.

Adds two nullable NUMERIC(20,8) columns to the ``holdings`` table and a
composite index on ``transactions(portfolio_id, executed_at, instrument_id)``
for efficient FIFO/AVCO replay queries.

Changes:
1. ``holdings.cost_basis_per_unit NUMERIC(20,8) NULL`` — FIFO/AVCO cost per
   share for MANUAL portfolio holdings. NULL for BROKERAGE/ROOT rows.
2. ``holdings.total_cost_basis NUMERIC(20,8) NULL`` — total cost of remaining
   lots (cost_basis_per_unit * quantity). NULL for BROKERAGE/ROOT rows.
3. ``CREATE INDEX CONCURRENTLY`` on ``transactions(portfolio_id, executed_at,
   instrument_id)`` — used by ComputeManualHoldingsUseCase's chronological
   replay query (§8 FR-3 performance requirement). CONCURRENTLY avoids a table
   lock on the transactions table during deployment (PLAN-0114 §15.1).

Safety:
- Both columns are additive nullable — no NOT NULL, no server_default needed;
  existing rows stay NULL and the ORM treats NULL as None.
- CONCURRENTLY index creation cannot run inside a transaction block. We wrap the
  CREATE/DROP INDEX CONCURRENTLY calls in ``op.get_context().autocommit_block()``
  which instructs Alembic to commit the preceding transaction, execute the DDL
  outside any transaction, and then start a new transaction for subsequent steps.
  This is the canonical pattern used across the codebase (see 0026 and
  intelligence-migrations/alembic/versions/0011_concurrent_alias_norm_index.py).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Add nullable cost-basis columns to holdings ────────────────────────
    # IDEMPOTENT GUARD (BP — alembic migrate-divergence): a sibling branch
    # applied this column DDL to the shared dev DB without recording the 0025
    # stamp (the DB stayed at 0024), so a re-run of ``upgrade head`` hit
    # ``DuplicateColumnError: column "cost_basis_per_unit" already exists`` and
    # exited 1. ``op.add_column`` is not idempotent, so we check the live schema
    # via the inspector and only add columns that are genuinely missing. This is
    # additive-only (R11) and safe to run on a DB at any point in 0024..0025.
    bind = op.get_bind()
    existing_cols = {col["name"] for col in sa.inspect(bind).get_columns("holdings")}
    if "cost_basis_per_unit" not in existing_cols:
        op.add_column(
            "holdings",
            sa.Column("cost_basis_per_unit", sa.Numeric(precision=20, scale=8), nullable=True),
        )
    if "total_cost_basis" not in existing_cols:
        op.add_column(
            "holdings",
            sa.Column("total_cost_basis", sa.Numeric(precision=20, scale=8), nullable=True),
        )

    # ── 2. CREATE INDEX CONCURRENTLY on transactions ──────────────────────────
    # WHY CONCURRENTLY: the transactions table is write-heavy during active
    # use; a standard CREATE INDEX would hold a ShareLock for the duration
    # of the build (minutes on large tables) and block all INSERTs.
    # CONCURRENTLY builds the index without a table lock at the cost of
    # requiring two table scans and not running inside a transaction.
    #
    # WHY autocommit_block: PostgreSQL raises
    #   "ERROR: CREATE INDEX CONCURRENTLY cannot run inside a transaction block"
    # if the DDL executes inside Alembic's default implicit transaction.
    # op.get_context().autocommit_block() commits the surrounding transaction
    # first, runs this DDL outside any transaction, then re-opens a transaction
    # for any subsequent steps. This is the canonical pattern in this codebase.
    # IF NOT EXISTS avoids a duplicate-index error on repeated migrations
    # (idempotent — safe to run twice).
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "ix_transactions_portfolio_executed_instrument "
                "ON transactions(portfolio_id, executed_at, instrument_id)"
            )
        )


def downgrade() -> None:
    # WHY autocommit_block: same constraint as upgrade — CONCURRENTLY cannot run
    # inside a transaction block. Drop index first (outside transaction), then
    # drop the nullable columns (inside the default transaction is fine).
    with op.get_context().autocommit_block():
        op.execute(sa.text("DROP INDEX CONCURRENTLY IF EXISTS ix_transactions_portfolio_executed_instrument"))
    op.drop_column("holdings", "total_cost_basis")
    op.drop_column("holdings", "cost_basis_per_unit")
