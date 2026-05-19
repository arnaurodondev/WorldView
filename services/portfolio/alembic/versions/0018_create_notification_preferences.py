"""Create ``notification_preferences`` table.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-19

W1-BACKEND: adds the per-tenant notification preference toggles required by
the frontend notification settings page (MED-022 / CRIT-004).

Table design:
  * ``tenant_id`` UUID PRIMARY KEY — one row per tenant (workspace-scoped).
  * Four boolean columns for the four alert categories, all NOT NULL with
    server default TRUE (opt-in by default — matches the application-layer
    defaults returned before the first row is written).
  * ``updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`` — tracks when
    preferences were last mutated.

Forward-compat (R5/R11):
  Adding a new table is always forward-compatible — old code that doesn't
  know about the table continues to work. New boolean columns have server
  defaults so any future INSERT that omits them remains valid.

Rollback:
  ``downgrade()`` drops the table — safe because the table has no incoming
  foreign keys from other tables and no data migration is required to remove
  it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        # WHY tenant_id as PK: one row per workspace — no surrogate key needed.
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        # price_alerts toggles flash-alert delivery for significant price moves.
        sa.Column("price_alerts", sa.Boolean(), nullable=False, server_default="true"),
        # news_alerts toggles news article arrival notifications.
        sa.Column("news_alerts", sa.Boolean(), nullable=False, server_default="true"),
        # movers_alerts toggles pre-market / intraday movers notifications.
        sa.Column("movers_alerts", sa.Boolean(), nullable=False, server_default="true"),
        # contradiction_alerts toggles KG contradiction signal delivery.
        sa.Column("contradiction_alerts", sa.Boolean(), nullable=False, server_default="true"),
        # updated_at records when the row was last mutated.
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("notification_preferences")
