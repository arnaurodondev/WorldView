"""Add period_type_* columns to instrument_fundamentals_snapshot — BP-542.

Revision ID: 020
Revises: 019
Create Date: 2026-05-26

PLAN-0095 T-W1-04 (EODHD deep-dive §5).

WHY THIS MIGRATION EXISTS:
  ``instrument_fundamentals_snapshot`` aggregates derived metrics (eps_ttm,
  free_cash_flow, fcf_margin, …) from three EODHD source sections
  (income_statement, cash_flow, balance_sheet). The current snapshot writer
  (``fundamentals_snapshot_writer._most_recent_financial_row``) prefers the
  most-recent ``yearly`` row but falls back to ``quarterly`` when no annual
  row exists. Without a periodicity column the snapshot caller cannot tell
  which periodicity each derived field was computed from — a stale-vs-fresh
  signal that operators and downstream consumers need.

WHAT THIS MIGRATION DOES:
  Adds three nullable VARCHAR(20) columns to
  ``instrument_fundamentals_snapshot``:
    * period_type_income     — periodicity of the source income_statement row
    * period_type_cash_flow  — periodicity of the source cash_flow row
    * period_type_balance    — periodicity of the source balance_sheet row

  Values are written by ``upsert_snapshot()`` on every consumer cycle. Old
  rows remain NULL until the next refresh — acceptable because the column is
  observability-only (no read path depends on it being NOT NULL).

DOWNGRADE: drops the three columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the three period_type_* tracking columns."""
    op.add_column(
        "instrument_fundamentals_snapshot",
        sa.Column("period_type_income", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "instrument_fundamentals_snapshot",
        sa.Column("period_type_cash_flow", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "instrument_fundamentals_snapshot",
        sa.Column("period_type_balance", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    """Drop the three tracking columns."""
    op.drop_column("instrument_fundamentals_snapshot", "period_type_balance")
    op.drop_column("instrument_fundamentals_snapshot", "period_type_cash_flow")
    op.drop_column("instrument_fundamentals_snapshot", "period_type_income")
