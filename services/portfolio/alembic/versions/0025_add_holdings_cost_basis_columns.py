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
- CONCURRENTLY index creation cannot run inside a transaction; alembic must
  skip the implicit transaction for this migration (``transaction_per_migration``
  is set to False via ``op.execute`` with the BEGIN/COMMIT stripped out by the
  ``connection.execute`` path).
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
    op.add_column(
        "holdings",
        sa.Column("cost_basis_per_unit", sa.Numeric(precision=20, scale=8), nullable=True),
    )
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
    # Alembic does not support CONCURRENTLY natively — we drop to raw DDL.
    # IF NOT EXISTS avoids a duplicate-index error on repeated migrations
    # (idempotent — safe to run twice).
    op.execute(
        sa.text(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_transactions_portfolio_executed_instrument "
            "ON transactions(portfolio_id, executed_at, instrument_id)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX CONCURRENTLY IF EXISTS ix_transactions_portfolio_executed_instrument"))
    op.drop_column("holdings", "total_cost_basis")
    op.drop_column("holdings", "cost_basis_per_unit")
