"""Add watchlists and watchlist_members tables; outbox performance index.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-20 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── watchlists ────────────────────────────────────────────────────────────
    op.create_table(
        "watchlists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "name", name="uq_watchlists_user_name"),
    )
    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"])
    op.create_index("ix_watchlists_tenant_id", "watchlists", ["tenant_id"])

    # ── watchlist_members ─────────────────────────────────────────────────────
    op.create_table(
        "watchlist_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("watchlist_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("watchlists.id"), nullable=False),
        # entity_id is intentionally NOT a FK to any other service table (R7)
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False, server_default="company"),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("watchlist_id", "entity_id", name="uq_watchlist_members_watchlist_entity"),
    )
    op.create_index("ix_watchlist_members_entity_id", "watchlist_members", ["entity_id"])
    op.create_index("ix_watchlist_members_watchlist_id", "watchlist_members", ["watchlist_id"])

    # ── outbox performance index (Gap E4) ─────────────────────────────────────
    op.create_index(
        "ix_outbox_events_status_lease_expires",
        "outbox_events",
        ["status", "lease_expires"],
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_status_lease_expires", table_name="outbox_events")
    op.drop_index("ix_watchlist_members_watchlist_id", table_name="watchlist_members")
    op.drop_index("ix_watchlist_members_entity_id", table_name="watchlist_members")
    op.drop_table("watchlist_members")
    op.drop_index("ix_watchlists_tenant_id", table_name="watchlists")
    op.drop_index("ix_watchlists_user_id", table_name="watchlists")
    op.drop_table("watchlists")
