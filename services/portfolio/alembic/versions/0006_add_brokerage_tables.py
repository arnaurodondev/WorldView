"""Add brokerage_connections and brokerage_sync_errors tables.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-10

Implements PLAN-0022 Wave A-2 — SnapTrade brokerage portfolio sync tables.
See PRD-0022 §6.4 for DDL specification.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. brokerage_connections (parent table) ────────────────────────────────
    op.create_table(
        "brokerage_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("snaptrade_user_id", sa.Text, nullable=False),
        sa.Column("snaptrade_user_secret", sa.Text, nullable=False),
        sa.Column("authorization_id", sa.Text, nullable=True),
        sa.Column("brokerage_name", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("snaptrade_tos_accepted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_sync_cursor", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_brokerage_connections_user_status", "brokerage_connections", ["user_id", "status"])
    op.create_index("ix_brokerage_connections_tenant_id", "brokerage_connections", ["tenant_id"])
    op.create_index("ix_brokerage_connections_portfolio_id", "brokerage_connections", ["portfolio_id"])

    # ── 2. brokerage_sync_errors (FK child) ───────────────────────────────────
    op.create_table(
        "brokerage_sync_errors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brokerage_connections.id"),
            nullable=False,
        ),
        sa.Column("snaptrade_transaction_id", sa.Text, nullable=False),
        sa.Column("error_type", sa.String(50), nullable=False),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("raw_transaction", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_brokerage_sync_errors_connection_created",
        "brokerage_sync_errors",
        ["connection_id", "created_at"],
    )
    op.create_index("ix_brokerage_sync_errors_error_type", "brokerage_sync_errors", ["error_type"])


def downgrade() -> None:
    # Drop FK child first, then parent
    op.drop_index("ix_brokerage_sync_errors_error_type", table_name="brokerage_sync_errors")
    op.drop_index("ix_brokerage_sync_errors_connection_created", table_name="brokerage_sync_errors")
    op.drop_table("brokerage_sync_errors")

    op.drop_index("ix_brokerage_connections_portfolio_id", table_name="brokerage_connections")
    op.drop_index("ix_brokerage_connections_tenant_id", table_name="brokerage_connections")
    op.drop_index("ix_brokerage_connections_user_status", table_name="brokerage_connections")
    op.drop_table("brokerage_connections")
