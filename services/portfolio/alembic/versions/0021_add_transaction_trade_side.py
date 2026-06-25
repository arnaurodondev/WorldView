"""Add trade_side column to transactions table.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-08

PLAN-0108 Wave 1: the frontend "Add Position" dialog sends
``transaction_type=TRADE`` together with ``trade_side=BUY|SELL`` so users
don't need to understand the INFLOW/OUTFLOW direction convention. The route
handler derives direction server-side (BUY → INFLOW, SELL → OUTFLOW) and
stores the original trade_side here for display purposes.

Forward-compatibility: nullable + no server_default means existing rows
(BUY, SELL, DIVIDEND, …) receive NULL, which the API serialises as ``null``
in the ``trade_side`` response field — the frontend already renders "—" for
absent optional fields.

Rollback: drops the column and its check constraint (no data loss — the
field is supplementary and derivable from direction).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "trade_side",
            sa.String(4),
            nullable=True,
            comment="BUY or SELL for TRADE-type transactions; NULL for all other types",
        ),
    )
    op.create_check_constraint(
        "ck_transactions_trade_side",
        "transactions",
        "trade_side IN ('BUY', 'SELL') OR trade_side IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_transactions_trade_side", "transactions", type_="check")
    op.drop_column("transactions", "trade_side")
