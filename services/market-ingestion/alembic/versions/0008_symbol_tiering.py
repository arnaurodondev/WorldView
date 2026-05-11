"""Add symbol_tiers table and tier/post_market_only columns to polling_policies.

Revision ID: 0008
Revises: 0002
Create Date: 2026-04-24

Changes:
  - Creates symbol_tiers table with UNIQUE(symbol, exchange)
  - Adds tier INTEGER NOT NULL DEFAULT 2 to polling_policies
  - Adds post_market_only BOOLEAN NOT NULL DEFAULT FALSE to polling_policies
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- symbol_tiers -----------------------------------------------------------
    op.create_table(
        "symbol_tiers",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("tier_source", sa.String(32), nullable=False, server_default="default"),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_user_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "exchange", name="uq_symbol_tiers_symbol_exchange"),
    )
    op.create_index("ix_symbol_tiers_tier", "symbol_tiers", ["tier"])

    # -- polling_policies: add tier and post_market_only columns ---------------
    op.add_column(
        "polling_policies",
        sa.Column("tier", sa.Integer(), nullable=False, server_default="2"),
    )
    op.add_column(
        "polling_policies",
        sa.Column("post_market_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("polling_policies", "post_market_only")
    op.drop_column("polling_policies", "tier")
    op.drop_index("ix_symbol_tiers_tier", table_name="symbol_tiers")
    op.drop_table("symbol_tiers")
