"""Add ``amount`` column to transactions for SnapTrade dividend/cash capture.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-28

PLAN-0046 Wave 1 / T-46-1-01.

Forward-compatible: column is NULLABLE with no server_default. Historical rows
remain NULL until the next brokerage sync re-ingests them. No backfill — the
SnapTrade adapter (BP-263) was previously dropping ``amount`` and ``fee`` from
``UniversalActivity``; on the next sync, dividend rows will populate this
column with the cash amount paid.

Why ``amount`` exists alongside ``fees``:
  * BUY/SELL: ``quantity * price`` plus ``fees`` is sufficient.
  * DIVIDEND: SnapTrade reports ``units≈0, price≈0, amount=<cash_paid>``.
    Without this column, dividend rows would persist as $0 and the frontend
    would show no income event.

See: docs/plans/0046-portfolio-correctness-and-analytics-plan.md (T-46-1-01)
     docs/audits/2026-04-28-qa-plan-0044-followup-report.md (F-002)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Alembic identifiers
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``amount`` column. Numeric(18,8) matches ``quantity``/``price`` precision."""
    op.add_column(
        "transactions",
        sa.Column("amount", sa.Numeric(18, 8), nullable=True),
    )


def downgrade() -> None:
    """Drop the ``amount`` column. Safe — column is nullable with no FK or index."""
    op.drop_column("transactions", "amount")
